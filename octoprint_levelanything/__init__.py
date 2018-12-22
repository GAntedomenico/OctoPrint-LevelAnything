# coding=utf-8
from __future__ import absolute_import
from octoprint.server import user_permission
from threading import Thread, Timer, Event
from time import time
import octoprint.plugin
import flask
import json
import math
import re

class LevelAnythingPlugin(octoprint.plugin.SettingsPlugin,
                     octoprint.plugin.AssetPlugin,
                     octoprint.plugin.TemplatePlugin,
                     octoprint.plugin.SimpleApiPlugin,
                     octoprint.plugin.StartupPlugin):

    # globals
    status = 'IDLE'
    profile = dict()
    profiles = dict()
    position = [float('nan'), float('nan'), float('nan'), 0.0]
    position_absolute = True
    extruder_absolute = True
    regex_coords = [
        re.compile('X([\-\d\.]+)', re.IGNORECASE),
        re.compile('Y([\-\d\.]+)', re.IGNORECASE),
        re.compile('Z([\-\d\.]+)', re.IGNORECASE),
        re.compile('E([\-\d\.]+)', re.IGNORECASE)
    ]
    output = ['X%.3f', 'Y%.3f', 'Z%.3f', 'E%.3f']
    regex_pos = re.compile('(?:ok )?X:([\-\d\.]+) Y:([\-\d\.]+) Z:([\-\d\.]+) E:([\-\d\.]+)')
    regex_probe = re.compile('Bed X: ([0-9\.\-]+) Y: ([0-9\.\-]+) Z: ([0-9\.\-]+)')
    command_event = command_regex = command_match = None

    def on_after_startup(self):
        # load saved profiles from settings for fast access
        self.profiles = json.loads(self._settings.get(['profiles']))
        # save a reference to the selected profile for extra fast access
        self.profile = self.profiles[self._settings.get(['selected_profile'])]

    def get_settings_defaults(self):
        return dict(
            profiles = json.dumps(dict(disabled = dict(
                matrix = [],
                matrix_updated = 0.0,
                min_x = 0,
                min_y = 0,
                max_x = 200,
                max_y = 200,
                count_x = 5,
                count_y = 5,
                offset_x = 0,
                offset_y = 0,
                offset_z = 0,
                lift = 0,
                lift_feed = 300,
                fade = 2,
                divide = 30,
                safe_homing = False,
                home_x = 100,
                home_y = 100,
                home_feed = 3000
            ))),
            selected_profile = 'disabled',
            response_timeout = 60.0,
            debug = False
        )
    
    def get_api_commands(self):
        return dict(
            probe_start = [], probe_cancel = [], profile_changed = []
        )
    
    def on_api_command(self, command, data):
        if not user_permission.can():
            from flask import make_response
            return make_response('Insufficient permissions', 403)
        if command == 'probe_start':
            self.profiles = json.loads(self._settings.get(['profiles']))
            self.profile = self.profiles[self._settings.get(['selected_profile'])]
            self.set_status('PROBING', 'Probing started')
            probe_thread = Thread(target = self.probe_start)
            probe_thread.start()
        elif command == 'probe_cancel':
            self.set_status('CANCEL', 'Probing cancelled, matrix not saved')
        elif command == 'profile_changed':
            self.profiles = json.loads(self._settings.get(['profiles']))
            self.profile = self.profiles[self._settings.get(['selected_profile'])]
        else:
            self._logger.info('Unknown command %s' % command)

    def probe_start(self):
        if self.profile['safe_homing']:
            # home first to prevent probe missing the bed
            # if safe homing is disabled, the user must home the carriage
            self.send_command('G28')

        # calculate distance between probe points
        dist_x = (self.profile['max_x'] - self.profile['min_x']) / float(self.profile['count_x'] - 1)
        dist_y = (self.profile['max_y'] - self.profile['min_y']) / float(self.profile['count_y'] - 1)

        # probe points and add to matrix
        matrix = []
        derivation = None
        for y in range(0, self.profile['count_y']):
            for x in range(0, self.profile['count_x']):
                # abort if status changed while executing the last loop (error occured or user clicked cancel)
                if self.status != 'PROBING':
                    return
                
                cmd = []
                # lift carriage if enabled
                if self.profile['lift'] > 0:
                    cmd.extend(['G91', 'G0 Z%.3f' % self.profile['lift']])

                # get the coordinates we want to probe
                point = [self.profile['min_x'] + dist_x * x, self.profile['min_y'] + dist_y * y, 0.0]
                self.set_status('PROBING', 'Probing point %d of %d...' % (
                    y * self.profile['count_x'] + x + 1, self.profile['count_x'] * self.profile['count_y']
                ))
                # send movement command and G30 to execute Z probe at position
                cmd.extend([
                    'G90',
                    'G0 X%.3f Y%.3f F%.3f' % (
                        point[0] + self.profile['offset_x'],
                        point[1] + self.profile['offset_y'],
                        self.profile['home_feed']
                    ),
                    'G30'
                ])
                if self._settings.get(['debug']):
                    # fake G30 response on virtual printer
                    cmd.append('!!DEBUG:send Bed X: %.3f Y: %.3f Z: %.3f' % (
                        point[0] + self.profile['offset_x'],
                        point[1] + self.profile['offset_y'],
                        0.5
                    ))
                response = self.send_command(cmd, self.regex_probe)
                if not response:
                    self.set_status('ERROR', 'Probing at location %.3f, %.3f timed out' % (point[0], point[1]))
                    return

                # extract result from regex match
                act_x = float(response.group(1)) - self.profile['offset_x']
                act_y = float(response.group(2)) - self.profile['offset_y']
                act_z = float(response.group(3))

                # marlin ignores shifted coordinates (G92) for G30, adapt coordinate space dynamically
                if derivation is None:
                    derivation = [act_x - point[0], act_y - point[1]]
                act_x, act_y = act_x - derivation[0], act_y - derivation[1]
                # compare the points we want to the actual position reported by the printer
                if not self.coords_equal(act_x, point[0], 0.1) or not self.coords_equal(act_y, point[1], 0.1):
                    self.set_status('ERROR',
                        'Probing failed: Coordinates mismatch, expected %.3f, %.3f, got %.3f, %.3f' %
                        (point[0], point[1], act_x, act_y)
                    )
                    return
                
                # write z offset into matrix
                point[2] = act_z

                # send probe result to front-end
                self.send_point(point)
                matrix.append(point)
        
        # matrix is now populated, save in settings
        self.profile['matrix'] = matrix
        self.profile['matrix_updated'] = time()
        self._settings.set(['profiles'], json.dumps(self.profiles))
        self._settings.save()

        # notify front-end with new data and status
        self.send_profile(self.profile)
        self.set_status('IDLE', 'Probing finished')

    # sends a command to the printer and waits for the specified response
    def send_command(self, command, responseRegex = None):
        if responseRegex is None:
            self._printer.commands(command)
            return None
        self.command_event = Event()
        self.command_regex = responseRegex
        self._printer.commands(command)
        result = self.command_event.wait(self._settings.get(['response_timeout']))
        if result:
            return self.command_match
        else:
            return None
    
    def on_gcode_received(self, comm, line, *args, **kwargs):
        if self.command_regex:
            self.command_match = self.command_regex.search(line)
            if self.command_match:
                self.command_regex = None
                self.command_event.set()
        return line

    def on_gcode_queuing(self, comm_instance, phase, cmd, cmd_type, gcode, subcode=None, tags=None, *args, **kwargs):
        if not gcode:
            # we don't have a G-Code here, do nothing
            return cmd

        # remove comment from command for processing
        index = cmd.find(';')
        comment = ''
        if index != -1:
            cmd = cmd[:index]
            comment = cmd[index:]

        # linear move
        if gcode in ('G0', 'G00', 'G1', 'G01'):
            # calculate z-offset at given position
            # first get X/Y/Z-coordinates from command
            # this is always executed for coordinate tracking
            match = [r.search(cmd) for r in self.regex_coords]
            target = []
            for i in range(4):
                if match[i]:
                    if self.position_absolute:
                        # absolute positioning, target position can be used directly
                        target.append(float(match[i].group(1)))
                    else:
                        # relative positioning, target position is relative to old position
                        target.append(self.position[i] + float(match[i].group(1)))
                else:
                    # if we don't have a new coordinate, the carriage stays at last coordinate
                    target.append(self.position[i])
            
            if match[3] and self.position_absolute and not self.extruder_absolute:
                # extruder uses relative coordinate override, correct here
                if math.isnan(self.position[3]):
                    target[3] = float(match[3].group(1))
                else:
                    target[3] = self.position[3] + float(match[3].group(1))

            # check if we need to calculate a z-offset
            if (len(self.profile['matrix']) == 0 or not self.position_absolute or
                (self.profile['fade'] > 0 and target[2] > self.profile['fade']) or
                True in [math.isnan(t) for t in target]):
                # store move target as current X/Y/Z
                self.position = target[:]
                # we have no matrix, it's a relative movement, we are above fading height,
                # or we don't have a valid target position; do nothing
                return

            # calculate move length, subdivide if necessary
            commands = []
            move_length = math.sqrt((self.position[0] - target[0]) ** 2 + (self.position[1] - target[1]) ** 2)
            # self._logger.info('Move length: %.3f' % move_length)
            if self.profile['divide'] > 0 and move_length > self.profile['divide']:
                # move is longer than subdivision setting, split into smaller moves
                factor = math.ceil(move_length / self.profile['divide'])
                # calculate move lengths of segments per axis based on current position
                lengths = [(target[i] - self.position[i]) / factor for i in range(len(target))]
                for n in range(1, int(factor) + 1):
                    move_point = [self.position[i] + lengths[i] * n for i in range(len(target))]
                    move_point[2] += self.get_z_offset(move_point[0], move_point[1], move_point[2])
                    commands.append(self.sub_coordinates(cmd, target, move_point))
            else:
                # modify with Z-offset
                move_point = target[:]
                move_point[2] += self.get_z_offset(move_point[0], move_point[1], move_point[2])
                commands.append(self.sub_coordinates(cmd, target, move_point))

            # store target as current X/Y/Z
            self.position = target[:]
            # return (divided) move
            return commands

        # home
        elif gcode == 'G28':
            # we don't know where the printer will move to, delete X/Y/Z
            self.delete_position()

            commands = []
            # always set Z-offset when homing
            commands.append('M851 Z%.3f' % self.profile['offset_z'])
            if self.profile['safe_homing']:
                if 'Z' not in cmd.upper() and ('X' in cmd.upper() or 'Y' in cmd.upper()):
                    # command homes X or Y but not Z, do not modify
                    commands.append(cmd + comment)
                    return commands
                # lift carriage if setting is positive
                if self.profile['lift'] > 0:
                    commands.extend([
                        'G91', # relative coordinates
                        'G0 Z%.3f F%.3f' % (self.profile['lift'], self.profile['lift_feed'])
                    ])
                # safe homing requires X and Y to be homed first
                commands.append('G28 X Y')
                # prepend movement command to Z-homing command
                commands.extend([
                    'G90', # absolute coordinates
                    'G0 X%.3f Y%.3f F%.3f' % ( # move
                        self.profile['home_x'] + self.profile['offset_x'],
                        self.profile['home_y'] + self.profile['offset_y'],
                        self.profile['home_feed']
                    ),
                    'G28 Z' # home Z
                ])
                if not self.position_absolute:
                    # reset to relative positioning if it was set before
                    commands.append('G91')

                # return new homing sequence
                return commands
            else:
                # no safe-homing required, just M851 and the original command
                commands.append(cmd + comment)
                return commands

        # auto level, use this plugin and suppress output to printer
        elif gcode == 'G29':
            self.on_api_command('probe_start', None)
            return (None, None)

        # move to matrix point
        elif gcode == 'G42':
            # this is not used often (if at all), performance is not a problem
            # compile regex patterns here
            matches = [
                re.search('I([\d]+)', cmd, re.IGNORECASE),
                re.search('J([\d]+)', cmd, re.IGNORECASE),
                re.search('F([\d\.]+)', cmd, re.IGNORECASE)
            ]
            values = [float(match.group(1)) if match else None for match in matches]
            if values[0] is not None and values[1] is not None:
                index = int(values[1]) * int(self.profile['count_x']) + int(values[0])
                if index >= 0 and index < len(self.profile['matrix']):
                    return 'G0 X%.3f Y%.3f%s' % (
                        self.profile['matrix'][index][0],
                        self.profile['matrix'][index][1],
                        ' F%.3f' % values[2] if values[2] else ''
                    )
            return (None, None)

        # positioning mode: absolute
        elif gcode == 'G90':
            self.position_absolute = True

        # positioning mode: relative
        elif gcode == 'G91':
            self.position_absolute = False
        
        # set X, Y, Z or E
        elif gcode == 'G92':
            match = [r.search(cmd) for r in self.regex_coords]
            for i in range(4):
                if match[i]:
                    self.position[i] = float(match[i].group(1))

        # extruder absolute
        elif gcode == 'M82':
            self.extruder_absolute = True

        elif gcode == 'M83':
            self.extruder_absolute = False

    def get_z_offset(self, x, y, z):
        # calculate surrounding matrix points
        dist_x = (self.profile['max_x'] - self.profile['min_x']) / float(self.profile['count_x'] - 1)
        dist_y = (self.profile['max_y'] - self.profile['min_y']) / float(self.profile['count_y'] - 1)
        index_x = (x - self.profile['min_x']) / dist_x
        index_y = (y - self.profile['min_y']) / dist_y
        # find out where the point is relative to the matrix
        index_nearby = []
        if x < self.profile['min_x']:
            if y < self.profile['min_y']:
                # point is top left of matrix
                index_nearby.append([0, 0])
            elif y > self.profile['max_y']:
                # point is bottom left of matrix
                index_nearby.append([0, self.profile['count_y'] - 1])
            else:
                # point is left of matrix
                index_nearby.append([0, math.floor(index_y)])
                index_nearby.append([0, math.ceil(index_y)])
        elif x > self.profile['max_x']:
            if y < self.profile['min_y']:
                # point is top right of matrix
                index_nearby.append([self.profile['count_x'] - 1, 0])
            elif y > self.profile['max_y']:
                # point is bottom right of matrix
                index_nearby.append([self.profile['count_x'] - 1, self.profile['count_y'] - 1])
            else:
                # point is right of matrix
                index_nearby.append([self.profile['count_x'] - 1, math.floor(index_y)])
                index_nearby.append([self.profile['count_x'] - 1, math.ceil(index_y)])
        else:
            if y < self.profile['min_y']:
                # point is top of matrix
                index_nearby.append([math.floor(index_x), 0])
                index_nearby.append([math.ceil(index_x), 0])
            elif y > self.profile['max_y']:
                # point is bottom of matrix
                index_nearby.append([math.floor(index_x), self.profile['count_y'] - 1])
                index_nearby.append([math.ceil(index_x), self.profile['count_y'] - 1])
            else:
                # point is inside matrix, use all 4 nearby points
                index_nearby = [
                    [ math.floor(index_x), math.floor(index_y) ],
                    [ math.ceil(index_x),  math.floor(index_y) ],
                    [ math.floor(index_x), math.ceil(index_y)  ],
                    [ math.ceil(index_x),  math.ceil(index_y)  ]
                ]            

        # get nearby points and their distance from our wanted point
        points_nearby = []
        for i in index_nearby:
            point = self.profile['matrix'][int(i[1]) * int(self.profile['count_x']) + int(i[0])]
            distance = math.sqrt((x - point[0]) ** 2 + (y - point[1]) ** 2)
            points_nearby.append(point + [distance])

        # calculate an average z-offset by distance from all found points
        average_z = 0.0
        total_distance = sum(p[3] for p in points_nearby)
        exact_matches = [p for p in points_nearby if p[3] == 0]
        if len(exact_matches) > 0:
            # one distance is 0, which means point matches exactly, use its value directly
            # and avoid division by zero in the else part
            average_z = exact_matches[0][2]
        else:
            # no distance is 0, calculate percentage factor of distance, the closer the higher
            total_factor = sum([total_distance / p[3] for p in points_nearby])
            for p in points_nearby:
                factor = total_distance / p[3] / total_factor
                average_z += p[2] * factor

        # apply fading height factor
        if self.profile['fade'] > 0 and z > 0:
            average_z *= 1 - z / self.profile['fade']

        return average_z

    def delete_position(self):
        self.position = [float('nan'), float('nan'), float('nan'), 0.0]

    # substitute coordinates in command with given values
    def sub_coordinates(self, command, original_target, coordinates):
        for i in range(4):
            if original_target[i] == coordinates[i]:
                # don't substitute already correct values
                continue
            match = self.regex_coords[i].search(command)
            if match:
                # coordinate match found, replace with new one
                command = command[:match.start()] + (self.output[i] % coordinates[i]) + command[match.end():]
            elif self.position[i] != coordinates[i]:
                # append coordinate, but only if it's a different value than the current one
                command = command + ' ' + (self.output[i] % coordinates[i])
        return command

    # set the status variable and send change to front-end
    def set_status(self, status, text):
        self.status = status
        self._plugin_manager.send_plugin_message(self._identifier, dict(status = status, text = text))
    
    # send a measured point to the UI
    def send_point(self, point):
        self._plugin_manager.send_plugin_message(
            self._identifier,
            dict(point = point)
        )

    def send_profile(self, profile):
        self._plugin_manager.send_plugin_message(self._identifier, dict(profile = profile))
    
    # compares two coordinates for equality with the given tolerance
    def coords_equal(self, float1, float2, tolerance = 0.1):
        return abs(float1 - float2) < tolerance

    def get_assets(self):
        return dict(
            js = ['js/levelanything.js'],
            css = ['css/levelanything.css']
        )

    def get_template_configs(self):
        return [
            dict(type = 'navbar', custom_bindings = False),
            dict(type = 'settings', custom_bindings = False)
        ]

    def get_update_information(self):
        return dict(
            levelanything = dict(
                displayName = 'LevelAnything',
                displayVersion = self._plugin_version,

                # version check: github repository
                type = 'github_release',
                user = 'TazerReloaded',
                repo = 'OctoPrint-LevelAnything',
                target = self._plugin_version,

                # update method: pip
                pip = 'https://github.com/TazerReloaded/OctoPrint-LevelAnything/archive/{target_version}.zip'
            )
        )

__plugin_name__ = 'LevelAnything'

def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = LevelAnythingPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        'octoprint.plugin.softwareupdate.check_config': __plugin_implementation__.get_update_information,
        'octoprint.comm.protocol.gcode.received': __plugin_implementation__.on_gcode_received,
        'octoprint.comm.protocol.gcode.queuing': __plugin_implementation__.on_gcode_queuing,
    }
