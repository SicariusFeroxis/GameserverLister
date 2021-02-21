import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime

from nslookup import Nslookup

parser = argparse.ArgumentParser(description='Retrieve a list of BF2Hub game servers and write it to a JSON file')
parser.add_argument('-g', '--gslist', help='Path to gslist binary', type=str, required=True)
parser.add_argument('-f', '--filter', help='Filter to apply to server list', type=str, default='')
parser.add_argument('-e', '--expired-ttl', help='How long to keep a server in list after it was last seen (in hours)', type=int, default=24)
args = parser.parse_args()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')

# Make sure gslist path is valid
if not os.path.isfile(args.gslist):
    sys.exit('Could not find gslist executable, please double check the provided path')

# Set paths
rootDir = os.path.dirname(os.path.realpath(__file__))
serverListFilePath = os.path.join(rootDir, 'bf2-servers.json')

# Manually look up servers.bf2hub.com to be able to spread retried across servers
lookerUpper = Nslookup()
dnsResult = lookerUpper.dns_lookup('servers.bf2hub.com')

# Run gslist and capture output
commandOk = False
tries = 0
maxTries = 3
gslistResult = None
while not commandOk and tries < maxTries:
    # Alternate between first and last found A record
    serverIp = dnsResult.answer[0] if tries % 2 == 0 else dnsResult.answer[-1]
    try:
        logging.info(f'Running gslist command against {serverIp}')
        gslistResult = subprocess.run([args.gslist, '-n', 'battlefield2', '-x', f'{serverIp}:28911',
                                       '-Y', 'battlefield2', 'hW6m9a', '-f', f'{args.filter}', '-o', '1'],
                                      capture_output=True, timeout=10)
        commandOk = True
    except subprocess.TimeoutExpired as e:
        logging.error(f'gslist timed out, try {tries + 1}/{maxTries}')
        tries += 1

# Make sure any server were found
# (gslist sends all output to stderr so check there)
if gslistResult is None or 'servers found' not in str(gslistResult.stderr):
    sys.exit('gslist could not retrieve any servers')

# Read gslist output file
logging.info('Reading gslist output file')
with open('battlefield2.gsl', 'r') as gslistFile:
    rawServerList = gslistFile.read()

# Init server list with servers from existing list or empty one
if os.path.isfile(serverListFilePath):
    with open(serverListFilePath, 'r') as serverListFile:
        logging.info('Reading servers from existing server list')
        servers = json.load(serverListFile)
else:
    servers = []

stats = {
    'serverTotalBefore': len(servers)
}

# Parse server list
# List format: [ip-address]:[port]
logging.info('Parsing server list')
for line in rawServerList.splitlines():
    elements = line.strip().split(':')
    server = {
        'ip': elements[0],
        'queryPort': elements[1],
        'lastSeenAt': datetime.now().astimezone().isoformat()
    }
    serverString = f'{server["ip"]}:{server["queryPort"]}'
    serverStrings = [f'{s["ip"]}:{s["queryPort"]}' for s in servers]
    if serverString not in serverStrings:
        logging.debug(f'Got new server {server["ip"]}:{server["queryPort"]}, adding it')
        servers.append(server)
    else:
        logging.debug(f'Got known server {server["ip"]}:{server["queryPort"]}, updating last seen at')
        servers[serverStrings.index(serverString)]['lastSeenAt'] = datetime.now().astimezone().isoformat()

# Iterate over copy of server list and remove any expired servers from the (actual) server list
logging.info(f'Checking server expiration ttl for {len(servers)} servers')
stats['expiredServersRemoved'] = 0
for index, server in enumerate(servers[:]):
    lastSeenAt = (datetime.fromisoformat(server['lastSeenAt']) if
                  'lastSeenAt' in server.keys() else datetime.min).astimezone()
    timePassed = datetime.now().astimezone() - lastSeenAt
    if timePassed.total_seconds() >= args.expired_ttl * 60 * 60:
        logging.debug(f'Server {server["ip"]}:{server["queryPort"]} has not been seen in {args.expired_ttl} hours, removing it')
        servers.remove(server)
        stats['expiredServersRemoved'] += 1

# Add current server total to stats
stats['serverTotalAfter'] = len(servers)

logging.info(f'Writing {len(servers)} servers to output file')
with open(serverListFilePath, 'w') as outputFile:
    json.dump(servers, outputFile)

logging.info(f'Run stats: {stats}')
