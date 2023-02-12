#!/usr/bin/env python3
'''
quectel_exporter -- Exporter for quectel modem 

quectel_exporter is a data exporter for Prometheus

@author:     Brendan Bank

@copyright:  2023 Brendan Bank. All rights reserved.

@license:    BSDv3

@contact:    brendan.bank ... gmail.com
@deffield    updated: Updated
'''

import sys, os, time
from os import path
import argparse
import serial, json
import re
import prometheus_client

import logging
from prometheus_client import Histogram, CollectorRegistry, start_http_server, Gauge, Info, generate_latest

FREQ_URL = "https://rahix.github.io/frequency-bands/data/fb.csv"

log = logging.getLogger(path.basename(__file__))
logging.basicConfig(format='%(name)s.%(funcName)s(%(lineno)s): %(message)s', stream=sys.stderr, level=logging.WARN)

__all__ = []
__version__ = 0.2
__date__ = '2023-01-10'
__updated__ = '2023-01-20'

EXPORTER_PORT = 9013
MODEMPORT = "/dev/ttyUSB2"
MODEMBAUDRATE = 115200
FREQDATA = {}
POLL_INTERVAL = 20

ACCESS_TECHNOLOGY = {"0": "GSM",
                     "2": "UTRAN",
                     "3": "GSM W/EGPRS",
                     "4": "UTRAN W/HSDPA",
                     "5": "UTRAN W/HSUPA",
                     "6": "UTRAN W/HSDPA and HSUPA",
                     "7": "E-UTRAN",
                     "100": "CDMA",
                     }

UE_STATE = {"SEARCH": "User Equipment is searching but could not (yet) find a suitable 2G/3G/4G cell.",
            "LIMSRV": "User Equipment is camping on a cell but has not registered on the network.",
            "NOCONN": "User Equipment is camping on a cell and has registered on the network, and it is in idle mode",
            "CONNECT": "User Equipment is camping on a cell and has registered on the network, and a call is in progress.",
            }

NEWORK_STATUS = {"0": "Not registered. ME is not currently searching a new operator to register to",
                 "1": "Registered, home network",
                 "2": "Not registered, but ME is currently searching a new operator to register to",
                 "3": "Registration denied",
                 "4": "Unknown",
                 "5": "Registered, roaming",
                 }

INFO_DATA = ['pin',
             'state',
             'state_txt',
             'connection_type',
             'is_tdd',
             'mcc',
             'mnc',
             'cellID',
             'pcid',
             'earfcn',
             'freq_band_ind',
             'freq_duplex_mode',
             'freq_note',
             'service_provider_name',
             'full_network_name',
             'short_network_name',
             'registered_public_land_mobile_network',
             'connection_status',
             'lac',
             'operator_num',
             'band',
             'network_time',
             'operator',
             'access_technology',
             'qccid',
             'imsi',
             'firmware',
             'model',
             'manufacturer',
             'imei_sn',
             'imei',
             'tac',
             'alphabet']

NUM_DATA = ['freq_operating_band',
            'freq_uplink_lower',
            'freq_uplink_upper',
            'freq_downlink_lower',
            'freq_downlink_upper',
            'ul_bandwidth',
            'dl_bandwidth',
            'rsrp',
            'rsrq',
            'rssi',
            'sinr',
            'channel',
            "battchg",
            "signal",
            "service",
            "call",
            "roam",
            "smsfull",
            "gprs_coverage",
            "callsetup",
            "bytes_sent",
            "bytes_recv"]


def COPS(text, data, string_name):
    txt = text[0].replace("+COPS: ", '')
    data_list = txt.split(',')
    if len(data_list) > 2:
        data['operator'] = data_list[2].replace('"', '')
        data['access_technology'] = ACCESS_TECHNOLOGY[data_list[3]]
    else:
        log.debug('+COPS: empty?')

    
def QENG(text, data, string_name):
    """
    '+QENG: "servingcell","NOCONN","LTE","FDD",222,88,586A512,18,125,1,4,4,8119,-107,-12,-74,12,-'
    "servingcell",<state>,"LTE",<is_tdd>,<mcc>,<mnc>,<cellID>,<pcid>,<earfcn>,<freq_band_ind>,<ul_bandwidth>,<dl_bandwidth>,<tac>,<rsrp>,<rsrq>,<rssi>,<sinr>,<srxlev>
    """
    strings = ["pre",
               "state",
               "connection_type",
               "is_tdd",
               "mcc",
               "mnc",
               "cellID",
               "pcid",
               "earfcn",
               "freq_band_ind",
               "ul_bandwidth",
               "dl_bandwidth",
               "tac",
               "rsrp",
               "rsrq",
               "rssi",
               "sinr",
               "srxlev"]
    
    bandwith = [1.4, 3, 5, 10, 15, 20]

    data_list = text[0].split(',')
    i = 1

    while i < len(strings):
        if strings[i] == 'srxlev':
            i = i + 1
            continue
        elif(strings[i] == 'ul_bandwidth' or strings[i] == 'dl_bandwidth'):
            data[strings[i]] = bandwith[int(data_list[i])]
        elif(strings[i] == 'freq_band_ind' and FREQDATA):
            data[strings[i]] = int(data_list[i])
            for header in FREQDATA[data_list[i]].keys():
                data["freq_" + header] = FREQDATA[data_list[i]][header]
                
        elif(strings[i] == 'cellID'):
            d = "0x" + data_list[i]
            data[strings[i]] = int(d, 0)
        elif(strings[i] == 'state'):
            data[strings[i]] = data_list[i].replace('"', '')
            data["state_txt"] = UE_STATE[data[strings[i]]]
        elif '"' in data_list[i] or data_list[i] == '-':
            data[strings[i]] = data_list[i].replace('"', '')
        else:
            data[strings[i]] = int(data_list[i])
        log.debug(f'transform {strings[i]} {data_list[i]} -> {data[strings[i]]}')
        i = i + 1

    return (data)


def VAR(text, data, string_name):
    result = re.search('\+[^:]*:(.*)', text[0])
    if result:
        data[string_name] = result.groups()[0].replace('"', '').replace(' ', '')
    else:
        data[string_name] = text[0]
    log.debug(f'transform {string_name} {text} -> {data[string_name]}')


def CREG(text, data, string_name):
    strings = ["pre", "connection_status", "lac", "ci", "Act"]
    ignore = ["pre", "ci", "Act"]
    
    data_list = text[0].split(',')
    
    i = 0

    while i < len(strings):
        if strings[i] in ignore:
            i = i + 1
            continue
        
        elif(strings[i] == 'connection_status'):
            log.debug (f"{strings[i]} = INT")
            data[strings[i]] = NEWORK_STATUS[data_list[i]]
        elif(strings[i] == 'lac'):
            log.debug (f"{strings[i]} = INT")
            data[strings[i]] = int(data_list[i].replace('"', ''))
            
        elif '"' in data_list[i] or data_list[i] == '-':
            data[strings[i]] = data_list[i].replace('"', '')
            log.debug (f"{strings[i]} = STRING")
        else:
            log.debug (f"{strings[i]} = INT")
            data[strings[i]] = int(data_list[i].replace('"', ''))
        
        log.debug(f'transform {strings[i]} {data_list[i]} -> {data[strings[i]]}')
        i = i + 1


def QNWINFO(text, data, string_name):
    """
        "QNWINFO": [
            "+QNWINFO: \"FDD LTE\",\"22288\",\"LTE BAND 3\",1650"
    """

    strings = ["act_string", "operator_num", "band", "channel"]
    
    data_list = text[0].replace("+QNWINFO: ", '').split(',')
    log.debug(f'{text} -> {data_list}')
    
    i = 1

    while i < len(strings):
        if(strings[i] == 'operator_num'):
            log.debug (f"{strings[i]} = INT")
            data[strings[i]] = int(data_list[i].replace('"', ''))

        elif '"' in data_list[i] or data_list[i] == '-':
            data[strings[i]] = data_list[i].replace('"', '')
            log.debug (f"{strings[i]} = STRING")
        else:
            log.debug (f"{strings[i]} = INT")
            data[strings[i]] = int(data_list[i].replace('"', ''))

        log.debug(f'transform {strings[i]} {data_list[i]} -> {data[strings[i]]}')
        i = i + 1
        

def QSPN(text, data, string_name):
    """
        "QSPN":
        "+QSPN: \"WINDTRE\",\"WINDTRE\",\"\",0,\"22288\""
    """
    strings = ["full_network_name", "short_network_name", "service_provider_name", "alphabet", "registered_public_land_mobile_network"]
    
    data_list = text[0].replace("+QSPN: ", '').split(',')
    log.debug(f'{text} -> {data_list}')
    
    i = 0

    while i < len(strings):
        if(strings[i] == 'rplmn'):
            log.debug (f"{strings[i]} = INT")
            data[strings[i]] = int(data_list[i].replace('"', ''))

        elif '"' in data_list[i] or data_list[i] == '-':
            data[strings[i]] = data_list[i].replace('"', '')
            log.debug (f"{strings[i]} = STRING")
        else:
            log.debug (f"{strings[i]} = INT")
            data[strings[i]] = int(data_list[i].replace('"', ''))

        log.debug(f'transform {strings[i]} {data_list[i]} -> {data[strings[i]]}')
        i = i + 1


def CIND(text, data, string_name):
    """
        "+CIND: 0,3,1,0,0,0,1,0"
        +CIND: ("battchg",(0-5)),("signal",(0-5)),("service",(0-1)),("call",(0-1)),("roam",(0-1)),("smsfull",(0-1)),("GPRS coverage",(0-1)),("callsetup",(0-3))
    
    

    """
    strings = ["battchg", "signal", "service", "call", "roam", "smsfull", "gprs_coverage", "callsetup"]
    
    data_list = text[0].replace("+CIND: ", '').split(',')
    
    log.debug(f'{text} -> {data_list}')
    
    i = 0

    while i < len(strings):
        if '"' in data_list[i] or data_list[i] == '-':
            data[strings[i]] = data_list[i].replace('"', '')
            log.debug (f"{strings[i]} = STRING")
        else:
            log.debug (f"{strings[i]} = INT")
            data[strings[i]] = int(data_list[i].replace('"', ''))

        log.debug(f'transform {strings[i]} {data_list[i]} -> {data[strings[i]]}')
        i = i + 1


def QGDCNT(text, data, string_name):
    """
    "+QGDCNT: 18346457,353683715"
    "QGDCNT": [
        "+QGDCNT: 18346457,353683715"
    """
    strings = ["bytes_sent", "bytes_recv"]
    
    data_list = text[0].replace("+QGDCNT: ", '').split(',')
    
    log.debug(f'{text} -> {data_list}')
    
    i = 0

    while i < len(strings):
        if '"' in data_list[i] or data_list[i] == '-':
            data[strings[i]] = data_list[i].replace('"', '')
            log.debug (f"{strings[i]} = STRING")
        else:
            log.debug (f"{strings[i]} = INT")
            data[strings[i]] = int(data_list[i].replace('"', ''))

        log.debug(f'transform {strings[i]} {data_list[i]} -> {data[strings[i]]}')
        i = i + 1


def CGDCONT(text, data, string_name):
    
    """
        "+CGDCONT: 1,\"IP\",\"internet.it\",\"0.0.0.0\",0,0,0,0",
        "+CGDCONT: 2,\"IPV4V6\",\"ims\",\"0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0\",0,0,0,0",
        "+CGDCONT: 3,\"IPV4V6\",\"\",\"0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0\",0,0,0,1"
        
        +CGDCONT: (1-24,100-179),"IP",,,(0-2),(0-4),(0-1),(0-1)
        +CGDCONT: (1-24,100-179),"PPP",,,(0-2),(0-4),(0-1),(0-1)
        +CGDCONT: (1-24,100-179),"IPV6",,,(0-2),(0-4),(0-1),(0-1)
        +CGDCONT: (1-24,100-179),"IPV4V6",,,(0-2),(0-4),(0-1),(0-1)

        
        "+CGACT: 1,1",
        "+CGACT: 2,0",
        "+CGACT: 3,0"
    """
    strings = ["cid", "PDP_type", "APN", "PDP_addr", "data_comp", "head_comp", "IPv4_addr_alloc", "request_type"]

    data['pdp'] = {}
    for line in text:
        data_dict = {}
        data_list = line.replace("+CGDCONT: ", '').split(',')
        i = 0
        while i < len(strings):
            if (strings[i] != 'cid'):
                data_dict[strings[i]] = data_list[i].replace('"', '')
            else:
                cid = data_list[i]
            i = i + 1
            
        data['pdp'][cid] = data_dict


def CGACT(text, data, string_name):
    strings = ["cid", "active"]
    
    data['pdp_active'] = {}
    for line in text:
        data_dict = {}
        data_list = line.replace("+CGACT: ", '').split(',')
        i = 0
        while i < len(strings):
            if (strings[i] != 'cid'):
                data_dict[strings[i]] = data_list[i].replace('"', '')
            else:
                cid = data_list[i]
                
            i = i + 1
            
        data['pdp_active'][cid] = data_dict

        
COMMANDS = {
    'pin': { 
        'cmd': 'AT+CPIN?',
        'description': 'SIM pin status',
        'run': VAR
    },
    'QENG': {
        'cmd': 'AT+QENG="SERVINGCELL"',
        'description': 'Report the information of serving cells, neighbor cells and packet switch parameters',
        'run': QENG
        },
    'QSPN': { 
        'cmd': 'AT+QSPN',
        'description': 'Display the Name of Registered Network',
        'run': QSPN
        },
    'CREG': {
        'precmd': 'AT+CREG=2',
        'cmd': 'AT+CREG?',
        'description': 'Network Registration Status',
        'run': CREG
    },
    'QNWINFO': {
        'cmd': 'AT+QNWINFO',
        'description': 'Network Information',
        'run': QNWINFO
    },
    'network_time': {
        'cmd': 'AT+QLTS',
        'description': 'Latest Time Synchronized Through Network',
        'run': VAR
    },
    'COPS': {
        'cmd': 'AT+COPS?',
        'description': 'Read Operator Names',
        'run': COPS
    },
    'QSIMSTAT': {
        'cmd': 'AT+QSIMSTAT?',
        'description': '(U)SIM Card Insertion Status Report'
    },
    'qccid': {
        'cmd': 'AT+QCCID',
        'description': '',
        'run': VAR
    },
    'imsi': {
        'cmd': 'AT+CIMI',
        'description': 'International Mobile Subscriber Identity (IMSI)',
        'run': VAR

    },
    'firmware': {
        'cmd': 'AT+GMR',
        'description': 'Firmware Revision Identification',
        'run': VAR

    },
    'model': {
        'cmd': 'AT+GMM',
        'description': 'Model Identification',
        'run': VAR
    },
    'manufacturer': {
        'cmd': 'AT+GMI',
        'description': 'Manufacturer Identification',
        'run': VAR

    },
    'imei_sn': {
        'cmd': 'AT+GSN=0',
        'description': 'International Mobile Equipment Identity (IMEI)',
        'run': VAR
    },
    'imei': {
        'cmd': 'AT+GSN=1',
        'description': 'International Mobile Equipment Identity (IMEI)',
        'run': VAR

    },
    'CGDCONT': {
        'cmd': 'AT+CGDCONT?',
        'description': 'PDP Context',
        'run': CGDCONT
    },
    'CGACT': {
        'cmd': 'AT+CGACT?',
        'description': 'PDP Context (active/Inactive)',
        'run': CGACT
    },
    'ATI': {
        'cmd': 'ATI',
        'description': 'Modem information'
    },
    'QGDCNT': {
        'cmd':'AT+QGDCNT?',
        'description': 'Packet counter',
        'run': QGDCNT
    },
    
    'CIND': {
        'cmd':'AT+CIND?',
        'description': 'Control Instructions',
        'run': CIND
        }
}


def main():
    '''main function.'''
    global FREQDATA

    program_name = os.path.basename(sys.argv[0])
    program_version = "v%s" % __version__
    program_build_date = str(__updated__)
    program_version_message = '%%(prog)s %s (%s)' % (program_version, program_build_date)
    program_shortdesc = __import__('__main__').__doc__.split("\n")[1]
    program_license = '''%s

  Created by Brendan Bank on %s.
  Copyright 2023 Brendan Bank. All rights reserved.

  Licensed under the BSD-3-Clause
  https://opensource.org/licenses/BSD-3-Clause

  Distributed on an "AS IS" basis without warranties
  or conditions of any kind, either express or implied.

USAGE''' % (program_shortdesc, str(__date__))

    # Setup argument parser
    parser = argparse.ArgumentParser(description=program_license, formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument("-v", "--verbose", dest="verbose", action="store_true", default=False,
                         help="set verbosity [default: %(default)s]")
    
    parser.add_argument('-V', '--version', action='version', version=program_version_message)
    
    parser.add_argument('-d', '--debug', action='store_true', dest="debug", default=False,
                        help="set debug [default: %(default)s]")
    
    parser.add_argument('-E', '--exporter-port', type=int, dest="exporter_port", default=EXPORTER_PORT,
                        help="set TCP Port for the exporter server [default: %(default)s]")

    parser.add_argument('-i', '--interval', type=int, dest="interval", default=POLL_INTERVAL,
                        help="Poll interval [default: %(default)s] seconds")

    parser.add_argument('-D', '--device', type=argparse.FileType('r'), dest="device", default=MODEMPORT,
                        help="set the path to the serial port of the modem [default: %(default)s]")

    parser.add_argument('-b', '--baudrate', type=int, dest="baudrate", default=MODEMBAUDRATE,
                        help="set the baudrate of the serial port of the modem [default: %(default)s]")
    
    parser.add_argument('-j', '--json', action="store_true", dest="json", default=False,
                        help="Read the defice file as json input: %(default)s]")
    
    parser.add_argument('-f', '--frequency', action="store_true", dest="frequency", default=False,
                        help="fetch frequency data from " + FREQ_URL + " : %(default)s]")
    
    parser.add_argument('-w', '--daemonize', action="store_true", dest="daemonize", default=False,
                        help="daemonize and listen on PORT to incoming requests. : %(default)s]")

    # Process arguments
    args = parser.parse_args()
    
    if (args.debug):
        log.setLevel(level=logging.DEBUG)
    elif (args.verbose):
        log.setLevel(level=logging.INFO)
    
    log.info (f'started with args {args}')
    
    if args.frequency:
        FREQDATA = getFreqdata()

    """ init prometheus_client """
    registry = prometheus_client.CollectorRegistry()

    lte_info = Info('lte_modem', 'LTE modem and connection info', labelnames=['port'], registry=registry)
    
    lte_pdp_info = Info('lte_modem_pdp', 'LTE modem pdp info', labelnames=['cid', 'port'], registry=registry)
    
    stats_list = {}
    for i in NUM_DATA:
        stats_list[i] = Gauge('lte_modem_' + i, i, labelnames=['port'], registry=registry)

    if args.daemonize:
        start_http_server(args.exporter_port, registry=registry)

    while True:

        data = getData(args)
        
        if (args.debug):
            log.debug(json.dumps(data, indent=4)) 
        
        stats = {}
        
        for cmd in COMMANDS.keys():
            if 'run' in COMMANDS[cmd]:
                log.debug(f'{cmd} has transform function')
                COMMANDS[cmd]['run'](data[cmd], stats, cmd)
        
        info = {}
        for i in INFO_DATA:
            if i in stats:
                info[i] = str(stats[i])
    
        lte_info.labels(args.device.name).info(info)
    
        for i in NUM_DATA:
            if i in stats:
                stats_list[i].labels(args.device.name).set(stats[i])
        
        for i in stats['pdp'].keys():
            stats['pdp'][i]['active'] = stats['pdp_active'][i]['active']
            lte_pdp_info.labels(i, args.device.name).info(stats['pdp'][i])
        
        if (args.debug):
            log.debug (json.dumps(stats, indent=4))

        log.info(f"Fetched data from lte modem on port: {args.device.name}: {stats['model']} rssi: {stats['rssi']} ")

        if not args.daemonize:
            print(generate_latest(registry=registry).decode())
            return(None)
        
        time.sleep(args.interval)
        

def readLine(signal, args):
    line = ""
    lines = []
    while line != 'OK' and line != 'ERROR':
        r = signal.readline().rstrip()
        log.debug(f'read "{r}" from {args.device.name}')
        line = r.decode("utf-8")
        if line == '' or line == 'OK':
            continue
        lines.append(line)
        
    return(lines)


def getData(args):

    if args.json:
        fp = open(args.device.name)
        json_obj = json.load(fp)
        return(json_obj)

    else:

        log.debug(f'open serial port {args.device.name}')
        modem = serial.Serial(
            port=args.device.name,
            baudrate=args.baudrate,
            timeout=2
        )
        log.debug(f'flush serial port {args.device.name}')
        modem.flushInput()
    
        data = {}
        for command in COMMANDS.keys():
            if "precmd" in COMMANDS[command]:
                log.debug(f"send prep command {COMMANDS[command]['precmd']} to {args.device.name}")
                cmd = COMMANDS[command]['precmd'] + "\r\n"
                modem.write(cmd.encode())
                lines = readLine(modem, args)
                
            log.debug(f"send {COMMANDS[command]['cmd']} to {args.device.name}")    
            cmd = COMMANDS[command]['cmd'] + "\r\n"
            modem.write(cmd.encode())
            lines = readLine(modem, args)
        
            data[command] = lines
        
        modem.close()
        
        return(data)


def getFreqdata():
    import urllib.request
    log.info(f'fetch data from {FREQ_URL}')
    try:
        with urllib.request.urlopen(FREQ_URL, timeout=5) as response:
            csv = response.read()
    except Exception as e:
        log.debug(f'Could not fecth {FREQ_URL}: {e}')
        return ({})
    lines = csv.decode("utf-8").split("\n")
    bands = {}
    
    header = lines[0].split(",")

    i = 1
    while i < len(lines):
        band = lines[i].split(",")
        if (len(band) == 1):
            i = i + 1
            continue

        freq = {}
        y = 0 
        while y < len(header):
            if header[y] in ['operating_band', 'duplex_mode', 'note']:
                freq[header[y]] = band[y]
            else:
                try:
                    freq[header[y]] = float(band[y])
                except Exception as e:
                    log.debug(f'Could not type cast {band[y]} to a float')
                    freq[header[y]] = 0

            y = y + 1
            
        bands[band[0]] = freq
        i = i + 1

    return (bands)
    

if __name__ == "__main__":

    sys.exit(main())
