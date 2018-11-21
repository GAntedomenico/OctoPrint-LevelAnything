$(function() {
    function LevelAnythingViewModel(parameters) {
        var self = this;

        // some globals (with type hint for vscode)
        /** @type {HTMLCANVASElement} */
        var CANVAS = $('#tab_plugin_levelanything CANVAS')[0];            
        var CTX = CANVAS.getContext('2d');
        var SIZE = CANVAS.width;
        var PADDING = 50;
        var DISABLED = 'disabled';
        var SETTINGS_VIEW_MODEL = parameters[0];

        // basic setup for canvas
        CTX.textAlign = 'center';
	    CTX.textBaseline = 'middle';
        CTX.font = '12px Arial';
        CTX.lineWidth = 2;
        CTX.strokeStyle = '#CCC';
        CTX.fillStyle = '#000';

        // front-end functions
        self.saveClick = function() {
            self.isProbing(true);
            var selectedProfile = self.profiles[self.selectedProfileName()];
            for (key in selectedProfile) if (selectedProfile.hasOwnProperty(key)) {
                if (typeof selectedProfile[key] == 'number') selectedProfile[key] = parseFloat(self.profile[key]());
                else selectedProfile[key] = self.profile[key]();
            }
            var data = { plugins: { levelanything: { profiles: JSON.stringify(self.profiles) } } };
            SETTINGS_VIEW_MODEL.saveData(data, function() {
                self.isProbing(false);
            });
        }
        self.probeStartClick = function() {
            self.profile.matrix([]);
            var selectedProfile = self.profiles[self.selectedProfileName()];
            for (key in selectedProfile) if (selectedProfile.hasOwnProperty(key)) {
                if (typeof selectedProfile[key] == 'number') selectedProfile[key] = parseFloat(self.profile[key]());
                else selectedProfile[key] = self.profile[key]();
            }
            var data = { plugins: { levelanything: { profiles: JSON.stringify(self.profiles) } } };
            SETTINGS_VIEW_MODEL.saveData(data, function() {
                self.sendJSON({ command: 'probe_start' });
            });
        }
        self.probeCancelClick = function() {
            self.sendJSON({ command: 'probe_cancel' });
        }
        // user clicked the add profile button, show modal
        self.addProfileClick = function() {
            self.newProfileName('');
            self.addProfileModal.modal('show');
        }
        // user clicked ok in the add profile dialog, create new profile
        self.addProfileOkClick = function() {
            if (!self.profiles[self.newProfileName()]) {
                // profile does not exist, create with values from disabled profile
                var newProfile = JSON.parse(JSON.stringify(self.profiles[DISABLED]));
                self.profiles[self.newProfileName()] = newProfile;
                var data = { plugins: { levelanything: { profiles: JSON.stringify(self.profiles) } } };
                SETTINGS_VIEW_MODEL.saveData(data, function() {
                    self.addProfileModal.modal('hide');
                    self.profileNames(Object.keys(self.profiles));
                    self.selectedProfileName(self.newProfileName());
                });
            }
        }
        // delete the currently selected profile
        self.removeProfileClick = function() {
            self.removeProfileModal.modal('show');
        }
        self.removeProfileOkClick = function() {
            delete self.profiles[self.selectedProfileName()];
            var data = { plugins: { levelanything: { profiles: JSON.stringify(self.profiles) } } };
            SETTINGS_VIEW_MODEL.saveData(data, function() {
                self.removeProfileModal.modal('hide');
                self.selectedProfileName(DISABLED);
                self.profileNames(Object.keys(self.profiles));
            });
        }
        // this is called before Knockout initializes the template,
        // define everything needed for templates here
        self.onBeforeBinding = function() {
            // for shorter access
            self.settings = SETTINGS_VIEW_MODEL.settings.plugins.levelanything;

            // load settings from config, unpacking the profiles object
            self.addProfileModal = $('#levelanything_modal_add');
            self.removeProfileModal = $('#levelanything_modal_remove');
            self.profiles = JSON.parse(self.settings.profiles());

            // populate template variables
            self.isDisabled = ko.observable(self.settings.selected_profile() == DISABLED);
            self.profileNames = ko.observableArray(Object.keys(self.profiles));
            self.isProbing = ko.observable(false);
            self.statusText = ko.observable();
            self.newProfileName = ko.observable('');
            self.selectedProfileName = ko.observable(self.settings.selected_profile());
            var selectedProfile = self.profiles[self.selectedProfileName()];

            // save the current profile as observables
            self.profile = {};
            for (key in selectedProfile) if (selectedProfile.hasOwnProperty(key)) {
                if (key == 'matrix') {
                    self.profile[key] = ko.observableMatrix(selectedProfile[key]);
                }
                else {
                    self.profile[key] = ko.observable(selectedProfile[key]);
                }
            }

            // subscribe for event when user changes profile selection
            self.selectedProfileName.subscribe(function(selected) {
                // update disabled observable which hides/disables controls when plugin is inactive
                self.isDisabled(selected == DISABLED);

                // update all values
                var selectedProfile = self.profiles[self.selectedProfileName()];
                for (key in self.profile) if (self.profile.hasOwnProperty(key)) {
                    self.profile[key](selectedProfile[key]);
                }

                // save currently selected profile to persist restarts
                var data = { plugins: { levelanything: { selected_profile: selected } } };
                SETTINGS_VIEW_MODEL.saveData(data, function() {
                    // notify back-end about profile change
                    self.sendJSON({command: 'profile_changed'});
                });
            });
        }
        // messages from python are processed here
        self.onDataUpdaterPluginMessage = function(plugin, message) {
            if (plugin != 'levelanything') return;
            else if (message.status) {
                self.statusText(message.text);
                self.isProbing(message.status == 'PROBING');
            }
            else if (message.point) {
                self.profile.matrix.push(message.point);
            }
            else if (message.profile) {
                // profile change from server, update local cache
                var selectedProfile = self.profiles[self.selectedProfileName()]
                for (key in selectedProfile) if (selectedProfile.hasOwnProperty(key)) {
                    self.profile[key](selectedProfile[key]);
                }
            }
        }
        // an observable implementation for displaying the probe matrix with live changes
        ko.observableMatrix = function (matrix) {
            var observable = ko.observableArray();
            observable.subscribe(function(matrix) {
                var selectedProfile = self.profiles[self.selectedProfileName()];
                CTX.clearRect(0, 0, SIZE, SIZE);
                CTX.strokeRect(1, 1, SIZE - 2, SIZE - 2);
                for (var i = 0; i < matrix.length; i++) {
                    factX = (SIZE - PADDING * 2) / (selectedProfile.max_x - selectedProfile.min_x);
                    factY = (SIZE - PADDING * 2) / (selectedProfile.max_y - selectedProfile.min_y);
                    CTX.fillText(
                        matrix[i][2],
                        (matrix[i][0] - selectedProfile.min_x) * factX + PADDING,
                        (matrix[i][1] - selectedProfile.min_y) * factY + PADDING
                    );
                }
            });
            observable(matrix);
            return observable;
        };
        // send a JSON command to python
        self.sendJSON = function(content) {
            $.ajax({
                url: API_BASEURL + 'plugin/levelanything',
                type: 'POST',
                dataType: 'json',
                data: JSON.stringify(content),
                contentType: 'application/json; charset=UTF-8'
            });
        }
    }
    OCTOPRINT_VIEWMODELS.push([
        LevelAnythingViewModel,
        ['settingsViewModel'],
        ['#tab_plugin_levelanything']
    ]);
});