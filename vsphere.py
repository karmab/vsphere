#!/usr/bin/env jython
"""
jython script to create Vmware Virtual Machines with cobbler support
"""

import optparse
import os
import sys
import xmlrpclib
import ConfigParser
from com.vmware.vim25 import *
from com.vmware.vim25.mo import *
import java.net.URL as URL

__author__ = "Karim Boumedhel"
__credits__ = ["Karim Boumedhel"]
__license__ = "GPL"
__version__ = "1.1"
__maintainer__ = "Karim Boumedhel"
__email__ = "karimboumedhel@gmail.com"
__status__ = "Production"

ERR_NOVSPHEREFILE="You need to create a correct vsphere.ini file in your home directory.Check documentation"
ERR_NOCOBBLERFILE="You need to create a correct cobbler.ini file in your home directory.Check documentation"
ERR_AUTHFAILED="Authentification failed"
ERR_CLIENTNOTFOUND="Client not found"
ERR_CLIENTNOCONF="Client not found in conf file"
ERR_CLIENTNOPROFILE="You need to create an ini file for all clients with defined profiles.Check documentation"
ERR_COBBLERMAC="Changevlan was specified but no cobblermac was defined in client ini file so not doing anything for this part"

#0-define auxiliary functions
def convert(octets):
 return str(float(octets)/1024/1024/1024)+"GB"

def dssize(ds):
 di=ds.getSummary()
 return convert(di.getCapacity()), convert(di.getFreeSpace())

def makecuspec(si,ori,dest,ip):
 specmanager=si.getCustomizationSpecManager()
 specmanager.duplicateCustomizationSpec(ori,dest)
 newspec=specmanager.getCustomizationSpec(dest)
 info=newspec.getInfo()
 info.setName(dest)
 info.setDescription(dest)
 newspec.setInfo(info)
 specdetails=newspec.getSpec()
 custoname=CustomizationFixedName()
 custoname.setName(dest)
 specdetails.getIdentity().setHostName(custoname)
 adapter=specdetails.getNicSettingMap()[0].getAdapter()
 adapter.getIp().setIpAddress(ip)
 specmanager.overwriteCustomizationSpec(newspec) 
 return specdetails
 

def createnicspec(nicname,netname,guestid,installnet=None):
 nicspec=VirtualDeviceConfigSpec()
 nicspec.setOperation(VirtualDeviceConfigSpecOperation.add)
 if guestid in ["rhel4guest","rhel4_64guest"]:
  #nic=VirtualPCNet32()
  nic=VirtualVmxnet()
 else:
  nic=VirtualVmxnet3()
 desc=Description()
 desc.setLabel(nicname)
 nicbacking=VirtualEthernetCardNetworkBackingInfo()
 if installnet:
  desc.setSummary(installnet)
  nicbacking.setDeviceName(installnet)
 else:
  desc.setSummary(netname)
  nicbacking.setDeviceName(netname)
 nic.setBacking(nicbacking)
 nic.setKey(0)
 nic.setDeviceInfo(desc)
 nic.setAddressType("generated")
 nicspec.setDevice(nic)
 return nicspec

def creatediskspec(disksize,ds,diskmode,thin=False):
 #SCSISPEC
 ckey=1000
 scsispec=VirtualDeviceConfigSpec()
 scsispec.setOperation(VirtualDeviceConfigSpecOperation.add)
 scsictrl=VirtualLsiLogicController()
 scsictrl.setKey(ckey)
 scsictrl.setBusNumber(0)
 scsictrl.setSharedBus(VirtualSCSISharing.noSharing)
 scsispec.setDevice(scsictrl)
 diskspec=VirtualDeviceConfigSpec()
 diskspec.setOperation(VirtualDeviceConfigSpecOperation.add)
 diskspec.setFileOperation(VirtualDeviceConfigSpecFileOperation.create)
 vd=VirtualDisk()
 vd.setCapacityInKB(disksize)
 diskspec.setDevice(vd)
 vd.setKey(0)
 vd.setUnitNumber(0)
 vd.setControllerKey(ckey);
 diskfilebacking=VirtualDiskFlatVer2BackingInfo()
 filename="["+ ds.getName() +"]"
 diskfilebacking.setFileName(filename)
 diskfilebacking.setDiskMode(diskmode)
 if thin:
  diskfilebacking.setThinProvisioned(True)
 else:
  diskfilebacking.setThinProvisioned(False)
 vd.setBacking(diskfilebacking)
 return scsispec,diskspec,filename


def createcdspec():
 #http://books.google.es/books?id=SdsnGmhF0QEC&pg=PA145&lpg=PA145&dq=VirtualCdrom%2Bspec&source=bl&ots=s8O2mw437-&sig=JpEo-AqmDV42b3fxpTcCt4xknEA&hl=es&sa=X&ei=KgGfT_DqApOy8QOl07X6Dg&redir_esc=y#v=onepage&q=VirtualCdrom%2Bspec&f=false
 cdspec=VirtualDeviceConfigSpec()
 cdspec.setOperation(VirtualDeviceConfigSpecOperation.add)
 cd=VirtualCdrom()
 cdbacking=VirtualCdromAtapiBackingInfo()
 sys.exit(0)
 cd.setBacking(cdbacking)               
 cd.setControllerKey(201)
 cd.setUnitNumber(0)
 cd.setKey(-1)
 cdspec.setDevice(cd)
 return cdspec 

def createclonespec(pool):
 clonespec=VirtualMachineCloneSpec()
 relocatespec=VirtualMachineRelocateSpec()
 relocatespec.setPool(pool.getMOR())
 clonespec.setLocation(relocatespec)
 clonespec.setPowerOn(False)
 clonespec.setTemplate(False)
 return clonespec

def stopvm(vm):
 if vm.getRuntime().getPowerState().toString()=="poweredOn":
  t=vm.powerOffVM_Task()
  result=t.waitForMe()
  print "%s powering off VM"% (result)

def startvm(vm):
 if vm.getRuntime().getPowerState().toString()=="poweredOff":
  t=vm.powerOnVM_Task(None)
  result=t.waitForMe()
  print "%s powering on VM"% (result)

def migratevm(vm,name,pool,host):
 print "migrating %s to %s "% (name,host.getName())
 t=vm.migrateVM_Task(pool,host,VirtualMachineMovePriority.highPriority,VirtualMachinePowerState.poweredOn)
 result=t.waitForMe()
 print "%s on migrating %s to %s "% (result,name,host.getName())


#-1-handle arguments
usage="script to create Vmware Virtual Machines with cobbler support"
version="1.1"
parser = optparse.OptionParser(usage=usage,version=version)

creationgroup = optparse.OptionGroup(parser, "Creation options")
creationgroup.add_option("-c", "--cpu", dest="numcpu", type="int", help="specify Number of CPUS")
creationgroup.add_option("-f", "--destnet", dest="destnet", type="string", help="specify Net to move net interface of VM to.By default,second interface and not first will be used, unless -6 option is set")
creationgroup.add_option("-m", "--memory", dest="memory", type="int", help="specify Memory, in Mo")
creationgroup.add_option("-n", "--name", dest="name",type="string", help="specify VM name")
creationgroup.add_option("-p", "--profile", dest="profile",type="string", help="specify Profile")
creationgroup.add_option("-d", "--size", dest="disksize", type="int", help="specify Disk size,in Go")
creationgroup.add_option("-t", "--template", dest="template", action="store_true", help="Deploy from template")
creationgroup.add_option("-C", "--client", dest="client", type="string", help="specify Client")
creationgroup.add_option("-D", "--datastore", dest="ds", type="string", help="specify Datastore")
creationgroup.add_option("-H", "--host", dest="host", type="string", help="specify ESX host to launch VM on.If no host is specified,an algorithm will be used to find best ESX to run the new VM -Currently the ESX with less running VMS will be choosen")
creationgroup.add_option("-I", "--installnet", dest="installnet", help="Use specific network at install time only.Correct net for second net interface will have to be put before first boot then.You can also use -A switch to force cobbler server to have its interface migrated to this installnet prior to deploying VM")
creationgroup.add_option("-O", "--diskmode", dest="diskmode", type="string", help="specify Disk mode.Defaults to persistent")
creationgroup.add_option("-T", "--thin", dest="thin", action="store_true", help="Use thin provisioning for disk")
creationgroup.add_option("-W", "--vlan", dest="changevlan", action="store_true", help="change VLAN of the cobbler server to match profile of the created machine.implies defining the associated MAC of the interface to change as cobblermac in cobbler.ini .By default,second interface of cobbler service will be used,unless -6 option is set")
creationgroup.add_option("-X", "--distributed", dest="distributed", action="store_true", help="Use portgroups members of a VirtualDistributedSwitch")
creationgroup.add_option("-Y", "--nolaunch", dest="nolaunch", action="store_true", help="Dont Launch VM,just create it")
parser.add_option_group(creationgroup)

actiongroup = optparse.OptionGroup(parser, "Action options")
actiongroup.add_option("-s", "--start", dest="start", action="store_true", help="Start VM")
actiongroup.add_option("-u", "--update", dest="update", action="store_true", help="Update VM(Cpu or Memory)")
actiongroup.add_option("-w", "--stop", dest="stop", action="store_true", help="Stop VM")
actiongroup.add_option("-F", "--forcekill", dest="forcekill", action="store_true", help="Dont ask confirmation when killing a VM")
actiongroup.add_option("-K", "--kill", dest="kill", type="string", help="specify VM to kill in virtual center.Confirmation will be asked unless -F/--forcekill flag is set.VM will also be killed in cobbler server if -Z/-cobbler flag set")
actiongroup.add_option("-M", "--migrate", dest="migrate", action="store_true", help="Migrate VM.host can be specified with -H or a list will be displayed")
actiongroup.add_option("-S", "--search", dest="search", type="string", help="Search VMS")
parser.add_option_group(actiongroup)

cobblergroup = optparse.OptionGroup(parser, "Cobbler options")
cobblergroup.add_option("-A", "--forceinstallnet", dest="forceinstallnet", action="store_true", help="Force cobbler server to have its interface migrated to this installnet prior to deploying VM")
cobblergroup.add_option("-P", "--pushcobbler", dest="pushcobbler", action="store_true", help="Push cobbler server to same ESX prior to install")
cobblergroup.add_option("-Z", "--cobbler", dest="cobbler", action="store_true", help="Cobbler support")
cobblergroup.add_option("-1", "--ip1", dest="ip1", type="string", help="specify first IP")
cobblergroup.add_option("-2", "--ip2", dest="ip2", type="string", help="specify second IP")
cobblergroup.add_option("-3", "--ip3", dest="ip3", type="string", help="specify third IP")
cobblergroup.add_option("-6", "--usefirst", dest="usefirst", action="store_true", help="use first interface instead of second when changing vlan")
parser.add_option_group(cobblergroup)

listinggroup = optparse.OptionGroup(parser, "Listing options")
listinggroup.add_option("-l", "--listprofiles", dest="listprofiles", action="store_true", help="list available profiles")
listinggroup.add_option("-L", "--listclients", dest="listclients", action="store_true", help="list available clients")
listinggroup.add_option("-R", "--report", dest="report", action="store_true", help="Report Overall info on VirtualCenter")
listinggroup.add_option("-V", "--listvms", dest="listvms", action="store_true", help="list all vms,along with theit status")

parser.add_option("-9", "--switchclient", dest="switchclient", type="string", help="Switch default client")
parser.add_option_group(listinggroup)

(options, args) = parser.parse_args()
clients=[]
bestesx={}
staticroutes=None
backuproutes=None
gwbackup=None
vcuser=None
cobbleruser=None
cobblermac=None
nextserver=None
destnet=options.destnet
changevlan=options.changevlan
usefirst=options.usefirst
client = options.client
diskmode = options.diskmode
disksize = options.disksize
distributed=options.distributed
ds=options.ds
host=options.host
installnet=options.installnet
forceinstallnet=options.forceinstallnet
ip1=options.ip1
ip2=options.ip2
ip3=options.ip3
kill=options.kill
forcekill=options.forcekill
listprofiles=options.listprofiles
listclients=options.listclients
listvms = options.listvms
switchclient = options.switchclient
memory = options.memory
memoryupdate = options.memory
migrate = options.migrate
pushcobbler = options.pushcobbler
name = options.name
cobbler=options.cobbler
nolaunch=options.nolaunch
numcpu = options.numcpu
numcpuupdate = options.numcpu
profile = options.profile
report = options.report
thin=options.thin
search=options.search
stop=options.stop
start=options.start
template=options.template
update=options.update
mac1="00:00:00:00:00:01"
mac2="00:00:00:00:00:02"
mac3="00:00:00:00:00:03"
guestid532="rhel5guest"
guestid564="rhel5_64Guest"
guestid632="rhel6guest"
guestid664="rhel6_64Guest"

vcconffile="%s/vsphere.ini" % (os.environ['HOME'])
#parse vsphere auth file
if not os.path.exists(vcconffile):
 print "Missing %s in your  home directory or in current directory.Check documentation" % vcconffile
 sys.exit(1)
try:
 c = ConfigParser.ConfigParser()
 c.read(vcconffile)
 vcs={}
 default={}
 for cli in c.sections():
  for option in  c.options(cli):
   if cli=="default":
    default[option]=c.get(cli,option)
    continue
   if not vcs.has_key(cli):
    vcs[cli]={option : c.get(cli,option)}
   else:
    vcs[cli][option]=c.get(cli,option)
except KeyError:
 print ERR_NOVSPHEREFILE
 os._exit(1)

if listclients:
 print "Available Clients:"
 for cli in  sorted(vcs):
  print cli
 if default.has_key("client"):print "Current default client is: %s" % (default["client"])
 sys.exit(0)

if switchclient:
 if switchclient not in vcs.keys():
  print "Client not defined...Leaving"
 else:
  mod = open(vcconffile).readlines()
  f=open(vcconffile,"w")
  for line in mod:
   if line.startswith("client"):
    f.write("client=%s\n" % switchclient)
   else:
    f.write(line)
  f.close()
  print "Default Client set to %s" % (switchclient)
 sys.exit(0)


if not client:
 try:
  client=default['client']
 except:
  print "No client defined as default in your ini file or specified in command line"
  os._exit(1)

#PARSE DEFAULT SECTION
try:
 if not numcpu:numcpu=int(default['numcpu'])
 if not diskmode:diskmode=default['diskmode']
 if not memory:memory=int(default['memory'])
 if not disksize:disksize=int(default['disksize'])
 if default.has_key('clientdir'):clientdir=default['clientdir']
 disksize = disksize*1048576
 disksizeg=convert(1000*disksize)
except:
 print "Problem parsing default section in your ini file"
 os._exit(1)
 

if client not in sorted(vcs):
 print "Client not defined.Use -L to list available clients"
 sys.exit(0)

try:
 vcip=vcs[client]['host']
 vcuser=vcs[client]['user']
 vcpassword=vcs[client]['password']
 dc=vcs[client]['datacenter']
except KeyError,e:
 print "Problem parsing your ini file:Missing parameter %s" % e
 os._exit(1)

#parse .cobbler auth file
if cobbler and client:
 if os.path.exists("cobbler.ini"):
  cobblerconffile="cobbler.ini"
 else:
  cobblerconffile=os.environ['HOME']+"/cobbler.ini"
 if not os.path.exists(cobblerconffile):
  print "Missing %s in your  home directory.Check documentation" % cobblerconffile
  sys.exit(1)
 try:
  c = ConfigParser.ConfigParser()
  c.read(cobblerconffile)
  cobblers={}
  for cli in c.sections():
   for option in  c.options(cli):
    if not cobblers.has_key(cli):
     cobblers[cli]={option : c.get(cli,option)}
    else:
     cobblers[cli][option]=c.get(cli,option)
  cobblerhost=cobblers[client]['host']
  cobbleruser=cobblers[client]['user']
  cobblerpassword=cobblers[client]['password']
  if cobblers[client].has_key("mac"):cobblermac=cobblers[client]['mac']
 except:
  print ERR_NOCOBBLERFILE
  os._exit(1)

if kill:
 if cobbler:
  s = xmlrpclib.Server("http://%s/cobbler_api" % cobblerhost)
  token = s.login(cobbleruser,cobblerpassword)
  system=s.find_system({"name":kill})
  if system==[]:
   print "%s not found in cobbler...Not doing anything at this level" % (kill)
  else:
   s.remove_system(kill,token)
   s.sync(token)
   print "%s sucessfully killed in %s" % (kill,cobblerhost)
 url="https://"+vcip+"/sdk"
 si = ServiceInstance(URL(url), vcuser, vcpassword , True)
 rootFolder=si.getRootFolder()
 vm=InventoryNavigator(rootFolder).searchManagedEntity("VirtualMachine",kill)
 if not vm:
  print "%s not found in VC...Not doing anything at this level" % (kill)
  sys.exit(0)
 else:
  if not forcekill:
   sure=raw_input("Confirm you want to kill VM %s (y|N):\n" % (kill))
   if sure!="Y":
    print "Not doing anything"
    sys.exit(1)
  stopvm(vm)
  t=vm.destroy_Task()
  result=t.waitForMe()
  print "%s on deleting %s in VC"% (result,kill)
 sys.exit(0)

#LIST VMS
if listvms:
 url="https://"+vcip+"/sdk"
 si = ServiceInstance(URL(url), vcuser, vcpassword , True)
 rootFolder=si.getRootFolder()
 vms=InventoryNavigator(rootFolder).searchManagedEntities("VirtualMachine")
 for vm in sorted(vms):print "%s %s" % (vm.getName(),vm.getRuntime().getPowerState().toString())
 sys.exit(0)




#SEARCH VMS
if search:
 url="https://"+vcip+"/sdk"
 si = ServiceInstance(URL(url), vcuser, vcpassword , True)
 rootFolder=si.getRootFolder()
 vms=InventoryNavigator(rootFolder).searchManagedEntities("VirtualMachine")
 vmfound=False
 for vm in vms:
  if search.replace("*","").upper() in vm.getName().upper():
   if not vmfound:print "Vms found:"
   print vm.getName()
   vmfound=True
 if not vmfound:print "No matching vms found"
 sys.exit(0)


#REPORT ABOUT VC
if report:
 url="https://"+vcip+"/sdk"
 si = ServiceInstance(URL(url), vcuser, vcpassword , True)
 rootFolder=si.getRootFolder()
 clus=InventoryNavigator(rootFolder).searchManagedEntities("ComputeResource")
 datacenters=InventoryNavigator(rootFolder).searchManagedEntities("Datacenter")
 print "Client: %s\n" % client
 for dc in datacenters:
  print "Datacenter: %s " % dc.getName()
 for clu in clus:
  print "Cluster: %s " % clu.getName()
  print "Associated Hosts:"
  for h in clu.getHosts():
   print "Host Name: %s HW: %s %s CPU: %s Memory: %sGb" % (h.getName(),h.getHardware().getSystemInfo().getVendor(),h.getHardware().getSystemInfo().getModel(),h.getHardware().getCpuInfo().getNumCpuCores(),h.getHardware().getMemorySize()/1024/1024/1024)
  print "Associated Networks:"
  for net in clu.getNetworks():
   print "Net Name: %s" % net.getName()
  print "Associated Datastores:"
  for ds in clu.getDatastores():
   print "DS Name: %s" % ds.getName()
  print ""
 sys.exit(0)

#INFO
if len(args) == 1:
 name=args[0]
 url="https://"+vcip+"/sdk"
 si = ServiceInstance(URL(url), vcuser, vcpassword , True)
 rootFolder=si.getRootFolder()
 hosts=InventoryNavigator(rootFolder).searchManagedEntities("HostSystem")
 if template:
  templates={}
  vms=InventoryNavigator(rootFolder).searchManagedEntities("VirtualMachine")
  for vm in vms:
   #if vm.getGuest().getGuestFamily()=="linuxGuest" and vm.getConfig().isTemplate():templates[vm.getName()]=vm
   if vm.getName()==name:
    print "Destination VM allready existing.Leaving..."
    sys.exit(1)
   if vm.getConfig().isTemplate():templates[vm.getName()]=vm
  print "Choose template to deploy VM from:"
  for templ in sorted(templates):print templ
  templatename=raw_input()
  if templatename not in templates.keys():
   print "Template not found.Leaving";sys.exit(1)
  template=templates[templatename]
  clusters={}
  clus=InventoryNavigator(rootFolder).searchManagedEntities("ComputeResource")
  for clu in clus:clusters[clu.getName()]=clu
  print "Choose Cluster to deploy VM on:"
  for c in sorted(clusters):print c
  clustername=raw_input()
  if clustername not in clusters.keys():
   print "Cluster not found.Leaving";sys.exit(1)
  clu=clusters[clustername]
  pool=clu.getResourcePool()
  clonespec=createclonespec(pool)
  t=template.cloneVM_Task(template.getParent(),name,clonespec)
  print "Deploying VM from template"
  result=t.waitForMe()
  print "%s on deploying %s from %s" %(result,name,templatename)
  sys.exit(0)
 vm=InventoryNavigator(rootFolder).searchManagedEntity("VirtualMachine",name)
 if not vm:
  print "%s not found,aborting" % (name)
  sys.exit(0)
 morhosts={}
 hostlist={}
 for h in hosts:
  morhosts[h.getMOR()]=h.getName()
  hostlist[h.getName()]=h
 if stop:
  stopvm(vm)
  sys.exit(0)
 if start:
  startvm(vm)
  sys.exit(0)
 currenthostname=morhosts[vm.getRuntime().getHost()]
 currenthost=hostlist[currenthostname]
 clus=InventoryNavigator(rootFolder).searchManagedEntities("ComputeResource")
 for clu in clus:
  for h in clu.getHosts():
   if h.toString()==currenthost.toString():
    clustername=clu.getName()
    cluster=clu
    break
    break
 if migrate:
  hostlist={}
  for hst in cluster.getHosts():
   if not hst.getSummary().getRuntime().isInMaintenanceMode():hostlist[hst.getName()]=hst
  if not host or host not in hostlist.keys():
   print "Choose a destination host:"
   #propose available hosts
   for h in hostlist.keys():print h
   host=raw_input()
   #check if host is within our keys or exit
   if not hostlist.has_key(host):
    print "Invalid Host"
    sys.exit(0)
  host=hostlist[host]
  pool=vm.getResourcePool()
  migratevm(vm,name,pool,host)
  sys.exit(0)
 if update:
  if not numcpuupdate and not memoryupdate:
   print "No new memory nor numcpu specified on command line.Leaving"
   sys.exit(0)
  cpu,mem=vm.getSummary().getConfig().getNumCpu(),vm.getSummary().getConfig().getMemorySizeMB()
  reconfig=False
  if numcpuupdate and numcpu!=cpu:reconfig=True
  if memoryupdate and memoryupdate!=mem:reconfig=True
  if reconfig:
   print "Reconfiguring VM.This will imply stopping it"
   sure=raw_input("Confirm you want to stop VM %s (y|N):\n" % (name))
   if sure!="Y":
    print "Not doing anything"
    sys.exit(1)
   stopvm(vm)
   #define specifications for reconfiguring VM
   reconfspec=VirtualMachineConfigSpec()
   if memoryupdate:reconfspec.setMemoryMB(memoryupdate)
   if numcpuupdate:reconfspec.setNumCPUs(numcpuupdate)
   print "Launching reconfiguration..."
   t=vm.reconfigVM_Task(reconfspec)
   result=t.waitForMe()
   print "%s reconfiguring %s"% (result,name)
   startvm(vm)
  sys.exit(0)
 if destnet:
  if distributed and net in portgs.keys():
   confspec=VirtualMachineConfigSpec()
   nicspec=VirtualDeviceConfigSpec()
   nicspec.setOperation(VirtualDeviceConfigSpecOperation.edit)
   nic=VirtualPCNet32()
   xnicbacking=VirtualEthernetCardDistributedVirtualPortBackingInfo()
   dvconnection=DistributedVirtualSwitchPortConnection()
   dvconnection.setSwitchUuid(portgs[net][0])
   dvconnection.setPortgroupKey(portgs[net][1])
   xnicbacking.setPort(dvconnection)
   nic.setBacking(xnicbacking)
   nicspec.setDevice(nic)
  else:
   confspec=VirtualMachineConfigSpec()
   nicspec=VirtualDeviceConfigSpec()
   nicspec.setOperation(VirtualDeviceConfigSpecOperation.edit)
   nic=VirtualPCNet32()
   xnicbacking=VirtualEthernetCardNetworkBackingInfo()
   xnicbacking.setDeviceName(destnet)
   nic.setBacking(xnicbacking)
   nicspec.setDevice(nic)
  devices=vm.getConfig().getHardware().getDevice()
  macaddr=[]
  coun=0
  for dev in devices:
   if "addressType" in dir(dev):
    if not usefirst:
     usefirst=True
     continue
    mac=dev.getMacAddress()
    dev.setBacking(xnicbacking)
    nicspec.setDevice(dev)
    devconfspec=[nicspec]
    confspec.setDeviceChange(devconfspec)
    t=vm.reconfigVM_Task(confspec)
    result=t.waitForMe()
    print "%s on migrating %s to vlan %s" %(result,name,destnet)
    break
  sys.exit(0)
 print "Name: %s"   % name
 #print "IP: %s " %vm.getGuest().getIpAddress()
 print "Cluster: %s"   % clustername
 print "Status: %s" % vm.getRuntime().getPowerState().toString()
 print "Os:%s" %  vm.getGuest().getGuestFullName()
 print "Host: %s"   % currenthostname
 cpu,mem=vm.getSummary().getConfig().getNumCpu(),vm.getSummary().getConfig().getMemorySizeMB()
 print "Memory: %sMb" % mem
 print "Cpus: %s"     % cpu
 nets=vm.getNetworks()
 dev=vm.getConfig().getHardware().getDevice()
 disks=[]
 nets={}
 for d in dev:
  if "E1000" in d.toString() or "Net" in d.toString() or "net" in d.toString():
   nettype=d.toString().replace("com.vmware.vim25.","").replace("Virtual","")
   try:
    netname=d.getBacking().getDeviceName()
   except:
    dvports={}
    dvnetworks=InventoryNavigator(rootFolder).searchManagedEntities("DistributedVirtualSwitch")
    for dvnetw in dvnetworks:
     uuid=dvnetw.getUuid()
     for portg in dvnetw.getPortgroup():dvports[portg.getKey()]=portg.getName()
    netnameid=d.getBacking().getPort().getPortgroupKey()
    netname=dvports[netnameid]
   netlabel=d.getDeviceInfo().getLabel()
   mac=d.getMacAddress()
   nets[netlabel]=[mac,netname,nettype]
  if "Disk" in d.toString():
   diskback=d.getBacking()
   datastore=diskback.getFileName().split(" ")[0]
   diskbacktype=diskback.toString()
   if "RawDiskMapping" in diskbacktype:
    disktype="RDM"
    thin=False
   else:
    disktype="Normal"
    thin=diskback.getThinProvisioned()
   cap=d.getCapacityInKB()
   disks.append([cap,disktype,thin])
 for disk in disks:
  size=disk[0]/1024/1024
  disktype=disk[1]
  thin=disk[2]
  print "disksize: %sGB type: %s thin: %s ds: %s" % (size,disktype,thin,datastore)
 for nic in sorted(nets):
  print "net interfaces: %s mac: %s net: %s type: %s " % (nic,nets[nic][0],nets[nic][1],nets[nic][2].split("@")[0])
 sys.exit(0)


#parse profile for specific client
if clientdir:
 clientconf="%s/%s.ini" % (clientdir,client)
else:
 clientconf="%s.ini" % client 

if not os.path.exists(clientconf):
 print "Missing %s.ini within this directory or within clientdir.Check documentation" % client
 sys.exit(1)
try:
 conffile=clientconf
 c = ConfigParser.ConfigParser()
 c.read(conffile)
 profiles={}
 for prof in c.sections():
  for option in  c.options(prof):
   if not profiles.has_key(prof):
    profiles[prof]={option : c.get(prof,option)}
   else:
    profiles[prof][option]=c.get(prof,option)
except:
 print ERR_CLIENTNOPROFILE
 os._exit(1)

if listprofiles:
 print "Use one of the availables profiles:"
 for profile in sorted(profiles.keys()): print profile
 sys.exit(0)

if not name:name=raw_input("enter machine s name:\n")
if cobbler:
 s = xmlrpclib.Server("http://%s/cobbler_api" % cobblerhost)
 token = s.login(cobbleruser,cobblerpassword)
 system=s.find_system({"name":name})
 if system!=[]:
  print "%s allready defined in cobbler...Use the following command if you plan to reinstall this machine:" % (name)
  print "%s -ZK %s -C %s" % (sys.argv[0],name,client)
  sys.exit(0)

if not profile:
 print "Choose a profile for your machine:"
 #propose available profiles
 for prof in profiles.keys():print prof
 profile=raw_input()
#check if profile is within our keys or exit
profiles.has_key(profile) or sys.exit(0)


#grab all conf from profile
clu=profiles[profile]['clu']
net1=profiles[profile]['net1']
net2=profiles[profile]['net2']
subnet1=profiles[profile]['subnet1']
subnet2=profiles[profile]['subnet2']
guestid=profiles[profile]['guestid']
if profiles[profile].has_key("nextserver"):nextserver=profiles[profile]['nextserver']
if profiles[profile].has_key("gwbackup"):gwbackup=profiles[profile]['gwbackup']
if profiles[profile].has_key("gwstatic"):gwstatic=profiles[profile]['gwstatic']
if profiles[profile].has_key("numinterfaces"):numinterfaces=int(profiles[profile]['numinterfaces'])
if profiles[profile].has_key("staticroutes"):staticroutes=profiles[profile]['staticroutes']

#grab nets 
if numinterfaces == 1:
 net1=profiles[profile]['net1']
 if installnet:
  nets=[installnet]
 else:
  nets=[net1]
elif numinterfaces == 2:
 net1=profiles[profile]['net1']
 net2=profiles[profile]['net2']
 if installnet:
  nets=[net1,installnet]
 else:
  nets=[net1,net2]
#cluster machines
elif numinterfaces == 3:
 net1=profiles[profile]['net1']
 net2=profiles[profile]['net2']
 net3=profiles[profile]['net3']
 if installnet:
  nets=[net1,installnet,net3]
 else:
  nets=[net1,net2,net3]

#grab ips and extra routes for cobbler
if cobbler:
 if numinterfaces == 1:
  if not subnet1:
   print "Missing subnet in client ini file.Check documentation"
   sys.exit(1)
  if not ip1:ip1=raw_input("Enter first ip:\n")
 elif numinterfaces == 2:
  if not subnet1 or not subnet2:
   print "Missing subnet in client ini file.Check documentation"
   sys.exit(1)
  if not ip1:ip1=raw_input("Enter first ip:\n")
  if not ip2:ip2=raw_input("Enter second ip:\n")
 #cluster machines
 elif numinterfaces == 3:
  if not subnet1 or not subnet2 or not subnet3:
   print "Missing subnet in client ini file.Check documentation"
   sys.exit(1)
  if not ip1:ip1=raw_input("Enter first ip:\n")
  if not ip2:ip2=raw_input("Enter second ip:\n")
  if not ip3:ip3=raw_input("Enter third ip:\n")
 if gwstatic and staticroutes:staticroutes=staticroutes.replace(",",":%s " % gwstatic)+":"+gwstatic
 if gwbackup and backuproutes:
  backuproutes=backuproutes.replace(",",":%s " % gwbackup)+":"+gwbackup
  staticroutes="%s %s" % (staticroutes,backuproutes)


 #3-create cobbler system 
 system = s.new_system(token)
 s.modify_system(system,'name',name,token)
 s.modify_system(system,'hostname',name,token)
 s.modify_system(system,'profile',profile,token)
 if nextserver:s.modify_system(system,'server',nextserver,token)

 if numinterfaces==1:
  if staticroutes:
   eth0={"macaddress-eth0":mac1,"static-eth0":1,"ipaddress-eth0":ip1,"subnet-eth0":subnet1,"staticroutes-eth0":staticroutes}
  else:
   eth0={"macaddress-eth0":mac1,"static-eth0":1,"ipaddress-eth0":ip1,"subnet-eth0":subnet1}
  s.modify_system(system,'modify_interface',eth0,token)
 elif numinterfaces==2:
  eth0={"macaddress-eth0":mac1,"static-eth0":1,"ipaddress-eth0":ip1,"subnet-eth0":subnet1}
  if staticroutes:
   eth1={"macaddress-eth1":mac2,"static-eth1":1,"ipaddress-eth1":ip2,"subnet-eth1":subnet2,"staticroutes-eth1":staticroutes}
  else:
   eth1={"macaddress-eth1":mac2,"static-eth1":1,"ipaddress-eth1":ip2,"subnet-eth1":subnet2}
  s.modify_system(system,'modify_interface',eth0,token)
  s.modify_system(system,'modify_interface',eth1,token)
 elif numinterfaces==3:
  eth0={"macaddress-eth0":mac1,"static-eth0":1,"ipaddress-eth0":ip1,"subnet-eth0":subnet1}
  if staticroutes:
   eth1={"macaddress-eth1":mac2,"static-eth1":1,"ipaddress-eth1":ip2,"subnet-eth1":subnet2,"staticroutes-eth1":staticroutes}
  else:
   eth1={"macaddress-eth1":mac2,"static-eth1":1,"ipaddress-eth1":ip2,"subnet-eth1":subnet2}
  eth2={"macaddress-eth2":mac3,"static-eth2":1,"ipaddress-eth2":ip3,"subnet-eth2":subnet3}
  s.modify_system(system,'modify_interface',eth0,token)
  s.modify_system(system,'modify_interface',eth1,token)
  s.modify_system(system,'modify_interface',eth2,token)
 s.save_system(system,token)	

nicname1 = "Network Adapter 1"
nicname2 = "Network Adapter 2"
nicname3 = "Network Adapter 3"
url="https://"+vcip+"/sdk"

#4-create vm 
#4-1-CONNECT
si = ServiceInstance(URL(url), vcuser, vcpassword , True)
rootFolder=si.getRootFolder()

#4-2-CREATEVM
dclist={}
hostlist={}
dslist={}
clusterlist={}
networklist={}
guestlist=[]

dc=InventoryNavigator(rootFolder).searchManagedEntity("Datacenter",dc)
clu=InventoryNavigator(rootFolder).searchManagedEntity("ComputeResource",clu)
pool=clu.getResourcePool()
vmfolder=dc.getVmFolder()

for hst in clu.getHosts():
 if not hst.getSummary().getRuntime().isInMaintenanceMode():hostlist[hst.getName()]=hst
 counter=0
 if not host:
  for vm in hst.getVms():
   if vm.getRuntime().getPowerState().toString()=="poweredOn":counter=counter+1
  bestesx[counter]=hst.getName()
 

if not host:
 host=bestesx[min(bestesx.keys())]
 print "%s selected as best ESX to launch new VM" % host
if not hostlist.has_key(host):
 print "ESX Host not found,aborting..."
 sys.exit(0)
host=hostlist[host]
if host.getSummary().getRuntime().isInMaintenanceMode():
 print "Selected Host is in maintenance mode.Use another..."
 sys.exit(0)

if not ds:print "Available DataStores:"
for dts in clu.getDatastores():
 if not ds: print dts.getName()+"\t"+dssize(dts)[0]+"\t"+dssize(dts)[1]
 dslist[dts.getName()]=dts
if not ds:ds=raw_input("Enter desired Datastore:\n")
if not dslist.has_key(ds):
 print "DataStore not found,aborting..."
 sys.exit(0)
#TODO:change this if to a test sum of all possible disks to be added to this datastore
if float(dssize(dslist[ds])[1].replace("GB","")) -float(disksizeg.replace("GB","")) <= 0:
 print "New Disk too large to fit in selected Datastore,aborting..."
 sys.exit(0)
ds=dslist[ds]


#define specifications for the VM
confspec=VirtualMachineConfigSpec()
confspec.setName(name)
confspec.setAnnotation(name)
confspec.setMemoryMB(memory)
confspec.setNumCPUs(numcpu)
confspec.setGuestId(guestid) 

scsispec,diskspec,filename=creatediskspec(disksize,ds,diskmode,thin)


#NICSPEC
if numinterfaces >= 1:
 #NIC 1
 nicspec1=createnicspec(nicname1,net1,guestid)
if numinterfaces >= 2:
 #NIC 2 (installnet will always be set only on this interface
  nicspec2=createnicspec(nicname2,net2,guestid,installnet)
if numinterfaces >= 3:
 #NIC 3
 nicspec3=createnicspec(nicname3,net3,guestid)

#cdspec=createcdspec()
if numinterfaces ==1:
 devconfspec=[scsispec, diskspec, nicspec1]
if numinterfaces ==2:
 devconfspec=[scsispec, diskspec, nicspec1,nicspec2]
if numinterfaces ==3:
 devconfspec=[scsispec, diskspec, nicspec1,nicspec2,nicspec3]

confspec.setDeviceChange(devconfspec)
vmfi=VirtualMachineFileInfo()
vmfi.setVmPathName(filename)
confspec.setFiles(vmfi)

t=vmfolder.createVM_Task(confspec,pool,None)
result=t.waitForMe()
print "%s on creation of %s" % (result,name)

#2-GETMAC
vm=InventoryNavigator(rootFolder).searchManagedEntity("VirtualMachine",name)
if not vm:
 print "%s not found,aborting" % (name)
 sys.exit(0)
devices=vm.getConfig().getHardware().getDevice()
macaddr=[]
for dev in devices:
 if "addressType" in dir(dev):
  macaddr.append(dev.getMacAddress())

if cobbler:
 if numinterfaces >= 1:
  eth0={"macaddress-eth0":macaddr[0]}
  s.modify_system(system,'modify_interface',eth0,token)
 if numinterfaces >= 2:
  eth1={"macaddress-eth1":macaddr[1]}
  s.modify_system(system,'modify_interface',eth1,token)
 if numinterfaces >= 3:
  eth2={"macaddress-eth2":macaddr[2]}
  s.modify_system(system,'modify_interface',eth2,token)
 s.sync(token)

#HANDLE DVS
if distributed:
 portgs={}
 dvnetworks=InventoryNavigator(rootFolder).searchManagedEntities("DistributedVirtualSwitch")
 for dvnetw in dvnetworks:
  uuid=dvnetw.getUuid()
  for portg in dvnetw.getPortgroup():portgs[portg.getName()]=[uuid,portg.getKey()]
 for k in range(len(nets)):
  net=nets[k]
  mactochange=macaddr[k]
  if net in portgs.keys():
   confspec=VirtualMachineConfigSpec()
   nicspec=VirtualDeviceConfigSpec()
   nicspec.setOperation(VirtualDeviceConfigSpecOperation.edit)
   nic=VirtualPCNet32()
   dnicbacking=VirtualEthernetCardDistributedVirtualPortBackingInfo()
   dvconnection=DistributedVirtualSwitchPortConnection()
   dvconnection.setSwitchUuid(portgs[net][0])
   dvconnection.setPortgroupKey(portgs[net][1])
   dnicbacking.setPort(dvconnection)
   nic.setBacking(dnicbacking)
   nicspec.setDevice(nic)
   #2-GETMAC
   vm=InventoryNavigator(rootFolder).searchManagedEntity("VirtualMachine",name)
   if not vm:
    print "%s not found,aborting" % (name)
    sys.exit(1)
   devices=vm.getConfig().getHardware().getDevice()
   for dev in devices:
    if "addressType" in dir(dev):
     mac=dev.getMacAddress()
     if mac==mactochange:
      dev.setBacking(dnicbacking)
      nicspec.setDevice(dev)
      devconfspec=[nicspec]
      confspec.setDeviceChange(devconfspec)
      t=vm.reconfigVM_Task(confspec)
      result=t.waitForMe()
      print "%s for changing DistributedVirtualSwitch for mac %s of %s" % (result,mac,name)


if profiles[profile].has_key("dhcp") and not installnet and cobbler:
 dhcp=profiles[profile]['dhcp']
 if numinterfaces == 1:
  mactochange=macaddr[0]
 else:
  mactochange=macaddr[1] 
 os.system("ssh %s \"sudo sed -i -e 's/hardware ethernet.*;/hardware ethernet %s;/' -e 's/fixed-address.*;/fixed-address %s;/' /etc/dhcpd.conf ;sudo /etc/init.d/dhcpd restart \"" % (dhcp,mactochange,ip2))


#5-MIGRATE COBBLER SERVER TO SAME ESX IF REQUESTED
if cobbler and pushcobbler:
 cobblervm=InventoryNavigator(rootFolder).searchManagedEntity("VirtualMachine",cobblerhost)
 if not cobblervm:
  print "Cobbler server %s not found,aborting" % (cobblerhost)
  sys.exit(1)
 t=cobblervm.migrateVM_Task(pool,host,VirtualMachineMovePriority.highPriority,VirtualMachinePowerState.poweredOn)
 result=t.waitForMe()
 print "%s on migrating %s to %s "% (result,cobblerhost,host.getName())

#MIGRATE COBBLER SERVER TO SAME VLAN 
if cobbler and ( changevlan or forceinstallnet):
 if cobblermac:
  if distributed and net in portgs.keys():
   confspec=VirtualMachineConfigSpec()
   nicspec=VirtualDeviceConfigSpec()
   nicspec.setOperation(VirtualDeviceConfigSpecOperation.edit)
   nic=VirtualPCNet32()
   xnicbacking=VirtualEthernetCardDistributedVirtualPortBackingInfo()
   dvconnection=DistributedVirtualSwitchPortConnection()
   dvconnection.setSwitchUuid(portgs[net][0])
   dvconnection.setPortgroupKey(portgs[net][1])
   xnicbacking.setPort(dvconnection)
   nic.setBacking(xnicbacking)
   nicspec.setDevice(nic)
  else:
   confspec=VirtualMachineConfigSpec()
   nicspec=VirtualDeviceConfigSpec()
   nicspec.setOperation(VirtualDeviceConfigSpecOperation.edit)
   nic=VirtualPCNet32()
   xnicbacking=VirtualEthernetCardNetworkBackingInfo()
   if usefirst:
    xnicbacking.setDeviceName(net1)
   else:
    xnicbacking.setDeviceName(net2)
   if installnet and forceinstallnet:
    xnicbacking.setDeviceName(installnet)
   nic.setBacking(xnicbacking)
   nicspec.setDevice(nic)
  #2-GETMAC
  cobblervm=InventoryNavigator(rootFolder).searchManagedEntity("VirtualMachine",cobblerhost)
  devices=cobblervm.getConfig().getHardware().getDevice()
  macaddr=[]
  for dev in devices:
   if "addressType" in dir(dev):
    mac=dev.getMacAddress()
    if mac==cobblermac:
     dev.setBacking(xnicbacking)
     nicspec.setDevice(dev)
     devconfspec=[nicspec]
     confspec.setDeviceChange(devconfspec)
     t=cobblervm.reconfigVM_Task(confspec)
     result=t.waitForMe()
     print "%s on migrating %s to same vlan" %(result,cobblerhost)
     break
 else:
  print ERR_COBBLERMAC

##set next server
##os.system("sed -i 's/next_server:.*/nextserver: %s/' /etc/cobbler/settings"  % (nextserver))
##s.sync(token)
# standardprompt="$"
# rootprompt="#"
# c = pexpect.spawn ("ssh %s" % (cobblerhost))
# #c.logfile = sys.stdout
# c.expect (standardprompt,timeout=10)
# c.sendline ('sudo -i')
# c.expect(rootprompt,timeout=10)
# c.sendline ("sed -i 's/next_server:.*/nextserver: %s/' /etc/cobbler/settings"  % (nextserver) )
# c.expect (rootprompt)
# s.sync(token)

if not nolaunch:
 #3-BOOTVM
 t=vm.powerOnVM_Task(host)
 result=t.waitForMe()
 print "%s on launching %s"% (result,name)
 #create a sumup file to be processed by companion programs for starting later the VM on the right network
 if installnet:
  f=open(name,"w")
  f.write("%s,%s,%s" % (name,net2,distributed))
  f.close()

si.getServerConnection().logout()

sys.exit(0)
