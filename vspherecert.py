#!/usr/bin/env python
"""
python script to retrieve basic ssl information from vcenters 
"""
#based on http://www.gefira.pl/blog/2011/07/06/fun-with-pythons-ssl-and-m2crypto-modules/

import optparse
import os
import sys
import ssl
from M2Crypto import X509
import ConfigParser

__author__ = "Karim Boumedhel"
__credits__ = ["Karim Boumedhel"]
__license__ = "GPL"
__version__ = "1.1"
__maintainer__ = "Karim Boumedhel"
__email__ = "karimboumedhel@gmail.com"
__status__ = "Production"

#-1-handle arguments
usage="script to create Vmware Virtual Machines with cobbler support"
version="1.1"
parser = optparse.OptionParser(usage=usage,version=version)

listinggroup = optparse.OptionGroup(parser, "Listing options")
listinggroup.add_option("-C", "--client", dest="client", type="string", help="specify Client")
listinggroup.add_option("-L", "--listclients", dest="listclients", action="store_true", help="list available clients")
listinggroup.add_option("-R", "--report", dest="report", action="store_true", help="Report Info on specified client")
parser.add_option("-9", "--switchclient", dest="switchclient", type="string", help="Switch default client")
parser.add_option_group(listinggroup)

(options, args) = parser.parse_args()
client = options.client
listclients = options.listclients
switchclient = options.switchclient
report = options.report

vcconffile = "%s/vsphere.ini" % (os.environ['HOME'])
#parse vsphere auth file
if not os.path.exists(vcconffile):
 print "Missing %s in your  home directory or in current directory.Check documentation" % vcconffile
 sys.exit(1)
try:
 c = ConfigParser.ConfigParser()
 c.read(vcconffile)
 vcs = {}
 default = {}
 for cli in c.sections():
  for option in  c.options(cli):
   if cli=="default":
    default[option] = c.get(cli,option)
    continue
   if not vcs.has_key(cli):
    vcs[cli] = {option : c.get(cli,option)}
   else:
    vcs[cli][option] = c.get(cli,option)
except KeyError:
 print ERR_NOVSPHEREFILE
 os._exit(1)

if listclients:
 print "Available Clients:"
 for cli in  sorted(vcs):
  print cli
 if default.has_key("client"):
    print "Current default client is: %s" % (default["client"])
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
  client = default['client']
 except:
  print "No client defined as default in your ini file or specified in command line"
  os._exit(1)

if client not in sorted(vcs):
 print "Client not defined.Use -L to list available clients"
 sys.exit(0)

try:
 vcip = vcs[client]['host']
except KeyError,e:
 print "Problem parsing your ini file:Missing parameter %s" % e
 os._exit(1)

if report:
    pem = ssl.get_server_certificate((vcip, 443))
    x509 = X509.load_cert_string(pem, X509.FORMAT_PEM)
    fp = x509.get_fingerprint('sha1')
    fp = ':'.join(fp[pos:pos+2] for pos in xrange(0, len(fp), 2))
    print('SHA1 fingerprint:\t%s' % fp)
    subject = x509.get_subject()
    print('Subject commonName:\t%s' % subject.CN)
