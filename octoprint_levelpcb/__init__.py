# coding=utf-8
from __future__ import absolute_import
from octoprint.server import user_permission
from threading import Timer
import octoprint.plugin
import random # for testing
import flask
import re

class LevelPCBPlugin(octoprint.plugin.SettingsPlugin,
                     octoprint.plugin.AssetPlugin,
                     octoprint.plugin.TemplatePlugin,
                     octoprint.plugin.SimpleApiPlugin):

    probePoints = []
    probePosition = -1
    probeTimer = None
    posX, posY = 0.0, 0.0

    def get_settings_defaults(self):
        return dict(
            probeWidth = 50, probeHeight = 50,
            pointsX = 5, pointsY = 5,
            offsetX = -26, offsetY = -40
        )

    def get_assets(self):
        return dict(
            js = ['js/levelpcb.js'],
            css = ['css/levelpcb.css']
        )

    def get_template_configs(self):
        return [
            dict(type = 'navbar', custom_bindings=False),
            dict(type = 'settings', custom_bindings=False)
        ]

    def get_template_vars(self):
        return dict(
            probeWidth = self._settings.get(['probeWidth']), probeHeight = self._settings.get(['probeHeight']),
            pointsX = self._settings.get(['pointsX']), pointsY = self._settings.get(['pointsY'])
        )

    def get_update_information(self):
        return dict(
            levelpcb=dict(
                displayName='LevelPCB',
                displayVersion=self._plugin_version,

                # version check: github repository
                type='github_release',
                user='TazerReloaded',
                repo='OctoPrint-LevelPCB',
                current=self._plugin_version,

                # update method: pip
                pip='https://github.com/TazerReloaded/OctoPrint-LevelPCB/archive/{target_version}.zip'
            )
        )

    def get_api_commands(self):
        return dict(probeStart=['probeWidth', 'probeHeight', 'pointsX', 'pointsY'])
    
    def on_api_command(self, command, data):
        if not user_permission.can():
            from flask import make_response
            return make_response('Insufficient rights', 403)
        if command == 'probeStart':
            self.probeStart(data['probeWidth'], data['probeHeight'], data['pointsX'], data['pointsY'])
        elif command == 'probeCancel':
            pass
        else:
            self._logger.info('Unknown command %s' % command)

    def probeStart(self, width, height, pointsX, pointsY):
        # clear probe points
        self.probePoints = []
        # calculate distance between probe points
        distX, distY = width / float(pointsX - 1), height / float(pointsY - 1)
        # fill array with probe points and a placeholder for the z-offset
        for y in range(0, pointsY):
            for x in range(0, pointsX):
                self.probePoints.append([distX * x, distY * y, 0.0])
        # get current printer position
        self.setProbeStatus('Querying printer position')
        self.probePosition = -2 # wait for 114
        self.startProbeTimer()
        self._printer.commands('M114')

    def onGcodeReceived(self, comm, line, *args, **kwargs):
        match = re.match('(?:ok )?X:([0-9\.\-]+) Y:([0-9\.\-]+) Z:([0-9\.\-]+)', line)
        if match and self.probePosition == -2:
            self.probePosition = 0
            self.posX = float(match.group(1)) + self._settings.get(['offsetX'])
            self.posY = float(match.group(2)) + self._settings.get(['offsetY'])

            # add current position offset to probe points
            self.probePoints = [[point[0] + self.posX, point[1] + self.posY, 0.0] for point in self.probePoints]

            # start timeout and send first probe command
            self.probeTimer.cancel()
            self.startProbeTimer()
            self.setProbeProgress()
            self._printer.commands('G30 X%.3f Y%.3f' % (self.probePoints[0][0], self.probePoints[0][1]))
            self._printer.commands('!!DEBUG:send Bed X: %.3f Y: %.3f Z: %.3f' % (
                self.probePoints[0][0], self.probePoints[0][1], random.random()
            ))

        match = re.match('Bed X: ([0-9\.\-]+) Y: ([0-9\.\-]+) Z: ([0-9\.\-]+)', line)
        # only evaluate matching command when probing is in progress (pos != -1)
        if match and self.probePosition >= 0:
            # extract result from regex match
            x, y, z = float(match.group(1)), float(match.group(2)), float(match.group(3))
            # compare the points wanted for the array with the actual position reported by the printer
            wantedX, wantedY = self.probePoints[self.probePosition][0], self.probePoints[self.probePosition][1]
            if self.coordsEqual(x, wantedX) and self.coordsEqual(y, wantedY):
                self.setProbeProgress()
                # probe successful, restart the probing timeout
                self.probeTimer.cancel()
                self.startProbeTimer()
                # write z offset into probe point array
                self.probePoints[self.probePosition][2] = z
                self.probePosition += 1
                # send probe result to front-end
                self._plugin_manager.send_plugin_message(self._identifier, dict(point = dict(
                    x = x - self.posX, y = y - self.posY, z = z
                )))
                if self.probePosition >= len(self.probePoints):
                    # position equals probe point count, stop timer and finish probing
                    self.probeTimer.cancel()
                    self.probePosition = -1
                    self.setProbeStatus('Probing finished')
                else:
                    # send next probe command to printer
                    self._printer.commands('G30 X%.3f Y%.3f' % (
                        self.probePoints[self.probePosition][0],
                        self.probePoints[self.probePosition][1]
                    ))
                    self._printer.commands('!!DEBUG:send Bed X: %.3f Y: %.3f Z: %.3f' % (
                        self.probePoints[self.probePosition][0],
                        self.probePoints[self.probePosition][1],
                        random.random()
                    ))

        # we need to return the unmodified line for display in terminal
        return line

    def startProbeTimer(self):
        self.probeTimer = Timer(30, self.onProbeTimerExpired)
        self.probeTimer.start()

    def onProbeTimerExpired(self):
        self.probePoints = []
        self.probePosition = -1
        self.setProbeStatus('Probing failed: timeout')

    # sets the current status message
    def setProbeStatus(self, text):
        self._plugin_manager.send_plugin_message(self._identifier, dict(status = text))

    # sets the status to a progress information text
    def setProbeProgress(self):
        self.setProbeStatus('Probing in progress (%d of %d)' % (self.probePosition + 1, len(self.probePoints)))

    # compares two coordinates for equality with 0.1mm tolerance
    def coordsEqual(self, float1, float2):
        return abs(float1 - float2) < 0.1

__plugin_name__ = 'LevelPCB'

def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = LevelPCBPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        'octoprint.plugin.softwareupdate.check_config': __plugin_implementation__.get_update_information,
        'octoprint.comm.protocol.gcode.received': __plugin_implementation__.onGcodeReceived
    }
