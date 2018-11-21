# OctoPrint-LevelAnything

Implements a mesh bed leveling system for OctoPrint, similar to ABL in Marlin, but a lot more flexible.
Can be used on the print bed, for milling, laser engraving and any other application where the surface might be uneven.

## Setup

Install via the bundled [Plugin Manager](http://docs.octoprint.org/en/master/bundledplugins/pluginmanager.html)
or manually using this URL:

    https://github.com/TazerReloaded/OctoPrint-LevelAnything/archive/master.zip

No special dependencies required, if OctoPrint runs fine, this plugin will too.

## Configuration

All configuration options are added as additional tab on the main UI. Currently, there is no extra settings page, because you'll want to access most options frequently.

## Plugin status and disclaimer

This plugin is still in active development, features may change, be added or removed in future releases. The plugin configuration might get deleted during updates, but I'll try my best to keep it.
**This plugin alters G-Code commands while they are sent to the printer. This could lead to errors in the printer's movement. I am not responsible for any damage caused by this plugin!**
On a correctly configured firmware the chances of catastrophic failure should be minimal, but if anything goes wrong: You have been warned, always watch your printer when trying anything new.
This plugin could also slow down your OctoPrint instance, because it performs quite a few calculations in the background for every movement command below the fading height. The code is written with performance in mind, and I didn't have any issues so far even with very complex models (Raspberry Pi 3).
