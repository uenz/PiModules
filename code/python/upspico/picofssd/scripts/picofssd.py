#!/usr/bin/python3

import sys

if (sys.platform == "linux") or (sys.platform == "linux2"):
    pass
else:
    # Replace libraries by fake ones
    import fake_rpi

    sys.modules['RPi'] = fake_rpi.RPi     # Fake RPi
    sys.modules['RPi.GPIO'] = fake_rpi.RPi.GPIO  # Fake GPIO
    sys.modules['smbus'] = fake_rpi.smbus  # Fake smbus (I2C)

from pimodules import configuration
from pimodules.alerts import sendEmail
from pimodules.daemon import Daemon
from gpiozero import Button, LED, Device
from gpiozero.pins.rpigpio import RPiGPIOFactory
from gpiozero.pins.lgpio import LGPIOFactory
from gpiozero.pins.pigpio import PiGPIOFactory
from gpiozero.pins.native import NativeFactory
import socket
import xmltodict
import argparse
import logging.handlers
import logging
import time
import atexit
import signal
import os
import threading
"""

PiModules(R) UPS PIco file-safe shutdown daemon.

"""


CLOCK_PIN = 'GPIO27'
PULSE_PIN = 'GPIO22'
BOUNCE_TIME = 0 #30.0/1000.0

#Device.pin_factory = RPiGPIOFactory()   # rpigpio
Device.pin_factory = LGPIOFactory()     # lgpio
# Device.pin_factory = PiGPIOFactory()    # pigpio
# Device.pin_factory = NativeFactory()    # native

class fssd(Daemon):
    def __init__(self, pidfile, xmlconfig, loglevel=logging.NOTSET):
        Daemon.__init__(self, pidfile)
        self.loglevel = loglevel
        self.log = logging.getLogger(__name__)
        self.log.setLevel(self.loglevel)
        self.log.setLevel(logging.DEBUG)
        if (sys.platform == "linux") or (sys.platform == "linux2"):
            handler = logging.handlers.SysLogHandler(address='/dev/log')
        else:
            handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter('%(module)s[%(process)s]: <%(levelname)s>: %(message)s')
        handler.setFormatter(formatter)
        self.log.addHandler(handler)

        try:
            self.xmlconfig = xmlconfig
            with open(self.xmlconfig, 'rb') as fi:
                self.config = xmltodict.parse(fi)
        except IOError as e:
            self.log.warning(
                "Failed to load XML config file, loading defaults. Alerts will be disabled")
            self.config = xmltodict.parse(configuration.DEFAULT_FSSD_XML_CONFIG)

        self.config = self.config['root']['fssd:config']['fssd:alerts']['fssd:email']
        self.config['fssd:enabled'] = (self.config['fssd:enabled'] == 'True')

        signal.signal(signal.SIGTERM, self.sigcatch)

        self.counter = 0
        self.mail_sent = False

        # first interrupt on isr pin will start pulse high
        self.sqwave = False
        self.lock = threading.Lock()

    def setup(self):
        """
        GPIO initialisation

        Note: This cannot go in the __init__ method because the unix double-fork in the generic daemon code
        mucks up the initialisation of the GPIO system.

        So it is called in the over-ridden run method.
        """


        ## GPIO.setup(CLOCK_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        self.clock_pin=Button(CLOCK_PIN,pull_up=True,bounce_time=BOUNCE_TIME)
        ## GPIO.setup(PULSE_PIN, GPIO.OUT, initial=self.sqwave)
        self.pulse_pin=LED(PULSE_PIN,initial_value=self.sqwave)
        print(f'pulse pin {self.pulse_pin.is_lit}')
        ## GPIO.add_event_detect(CLOCK_PIN, GPIO.FALLING, callback=self.isr, bouncetime=BOUNCE_TIME)
        self.clock_pin.when_pressed=self.isr

    def isr(self):
        """
        GPIO interrupt service routine
        """
        ## This test is here because the user *might* have another HAT plugged in or another circuit that produces a
        ## falling-edge signal on another GPIO pin.
        ## if channel != CLOCK_PIN:
        ##    return
        print('irq')
        with self.lock:
            print('irq - lock')
            # we can get the state of a pin with GPIO.input even when it is currently configured as an output
            #self.sqwave = not GPIO.input(PULSE_PIN)
            print(f'{self.sqwave}')
            self.sqwave = not self.pulse_pin.is_lit
            print(f'{self.sqwave}')

            # set pulse pin low before changing it to input to look for shutdown signal
            ## GPIO.output(PULSE_PIN, False)
            self.pulse_pin.off()
            self.pulse_pin.close()
            ## GPIO.setup(PULSE_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
#            self.pulse_pin=Button(PULSE_PIN,pull_up=True)
            # if not GPIO.input(PULSE_PIN):
#            if self.pulse_pin.is_pressed:            
                # disable irq to prevent multiple mails
                ## GPIO.remove_event_detect(CLOCK_PIN)
#                self.clock_pin.when_pressed=None
#                self.clock_pin.close()
#                print('irq - button not pressed')
                # pin is low, this is shutdown signal from pico
#                self.counter += 1
#                self.log.warning("Lost power supply, Pi will shutdown")
#                if self.mail_sent == False:
#                    self.mail_sent = True
#                    self.alert_email()
#                time.sleep(2)
#                os.system('/sbin/shutdown -h now')
#            else:
#                print('irq - button not pressed')
#                self.counter = 0

            # change pulse pin back to output with flipped state
            ## GPIO.setup(PULSE_PIN, GPIO.OUT, initial=self.sqwave)
            self.pulse_pin.close()
            self.pulse_pin=LED(PULSE_PIN,initial_value=self.sqwave)
            print(f'pulse pin {self.pulse_pin.is_lit}')
            print(f'irq - lock release {self.sqwave}')
            print('irq - out')


    def sigcatch(self, signum, frame):
        """
        Signal handler
        """

        if signum == signal.SIGTERM:
            sys.exit(0)

    def cleanup(self):
        """
        GPIO cleanup
        """

        self.log.debug("Cleanup")
        self.log.info("Stopped")
        ## GPIO.cleanup()
        try:
         self.pulse_pin.close()
         self.clock_pin.close()

        finally:
          pass
    def alert_email(self):
        # emailserver, username, port, security, fromAddr, toAddr, b64Password, msgSubjectTemplate, msgBodyTemplate
        try:
            if not self.config['fssd:enabled']:
                self.log.debug("Email alert is disabled")
                return True

            sendEmail(self.config['fssd:server'], self.config['fssd:username'], self.config['fssd:port'], self.config['fssd:security'],
                      self.config['fssd:sender-email-address'], self.config['fssd:recipient-email-address'],
                      self.config['fssd:sender-password'], self.config['fssd:subject-template'],
                      self.config['fssd:body-template'])
        except socket.error as e:
            self.log.error(format("Exception in alert_email: %d, %s" % (e.errno, e.strerror)))
        except:
            self.log.error("Unexpected error in alert_email:", sys.exc_info()[0])

    def run(self):
        """
        Super-class overloaded run method.
        """
        self.log.info("Started")
        self.log.debug(self.config['fssd:enabled'])
        self.log.debug(self.config['fssd:server'])
        self.log.debug(self.config['fssd:username'])
        self.log.debug(self.config['fssd:sender-email-address'])
        self.log.debug(self.config['fssd:recipient-email-address'])

        # register function to cleanup at exit
        atexit.register(self.cleanup)

        self.setup()

        while True:
            time.sleep(5)

if __name__ == "__main__":
    # parse the command-line
    parser = argparse.ArgumentParser()
    parser.add_argument('-l', '--log-level', help="Log level, 'info' or 'debug'",
                        default='info', choices=['info', 'debug'])
    parser.add_argument("-x", "--xml-config", help="XML config file",
                        default='picofssd.xml', required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-d", "--debug", help="Keep in the foreground, do not daemonize",
                    action="store_true", default=False)
    group.add_argument("-p", "--pid-file", help="PID file")
    args = parser.parse_args()
    print("args")
    sd = fssd(args.pid_file, args.xml_config, {
            'info': logging.INFO, 'debug': logging.DEBUG}[args.log_level])
    # the argument to the start method is opposite of debug
    sd.start(not args.debug)
