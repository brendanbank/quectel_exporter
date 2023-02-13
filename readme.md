	
	usage: quectel.py [-h] [-v] [-V] [-d] [-E EXPORTER_PORT] [-i INTERVAL] [-D DEVICE] [-b BAUDRATE] [-j] [-f] [-w] [-u, USERNAME] [-g, GROUP]
	
	quectel_exporter -- Exporter for quectel modem 
	
	  Created by Brendan Bank on 2023-01-10.
	  Copyright 2023 Brendan Bank. All rights reserved.
	
	  Licensed under the BSD-3-Clause
	  https://opensource.org/licenses/BSD-3-Clause
	
	  Distributed on an "AS IS" basis without warranties
	  or conditions of any kind, either express or implied.
	
	USAGE
	
	options:
	  -h, --help            show this help message and exit
	  -v, --verbose         set verbosity [default: False]
	  -V, --version         show program's version number and exit
	  -d, --debug           set debug [default: False]
	  -E EXPORTER_PORT, --exporter-port EXPORTER_PORT
	                        set TCP Port for the exporter server [default: 9013]
	  -i INTERVAL, --interval INTERVAL
	                        Poll interval [default: 20] seconds
	  -D DEVICE, --device DEVICE
	                        set the path to the serial port of the modem [default: /dev/ttyUSB2]
	  -b BAUDRATE, --baudrate BAUDRATE
	                        set the baudrate of the serial port of the modem [default: 115200]
	  -j, --json            Read the defice file as json input: False]
	  -f, --frequency       fetch frequency data from https://rahix.github.io/frequency-bands/data/fb.csv : False]
	  -w, --daemonize       daemonize and listen on PORT to incoming requests. : False]
	  -u, USERNAME, --username USERNAME
	                        Run the exporter as a specific user drop. The exporter must be started as root to enable this. [default: nobody]
	  -g, GROUP, --group GROUP
	                        Run the exporter as a specific group. The exporter must be started as root to enable this. [default: dialout]
