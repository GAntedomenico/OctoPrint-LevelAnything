$(function() {
    function LevelPCBViewModel(parameters) {
        var self = this;

        self.settingsModel = parameters[0];
        self.probeWidth = ko.observable();
        self.probeHeight = ko.observable();
        self.probeStatus = ko.observable('Ready');
        self.pointsX = ko.observable();
        self.pointsY = ko.observable();

        /** @type {HTMLCanvasElement} */
        var canvas = $('#tab_plugin_levelpcb canvas')[0];            
        var ctx = canvas.getContext('2d');
        var size = canvas.width;
        var padding = 50;

        ctx.textAlign = 'center';
	    ctx.textBaseline = 'middle';
        ctx.font = '12px Arial';
        ctx.lineWidth = 2;
        ctx.strokeStyle = '#CCC';
        ctx.fillStyle = '#000';

        self.probeStart = function() {
            ctx.clearRect(0, 0, size, size);
            ctx.beginPath();
            ctx.strokeRect(1, 1, size - 2, size - 2);
            self.sendJSON({
                command: 'probeStart',
                probeWidth: parseFloat(self.probeWidth()),
                probeHeight: parseFloat(self.probeHeight()),
                pointsX: parseInt(self.pointsX()),
                pointsY: parseInt(self.pointsY())
            });
        }
        
        self.probeCancel = function() {
            self.sendJSON({ command: 'probeCancel' });
        }

        self.onBeforeBinding = function() {
            var settings = self.settingsModel.settings;
            self.probeWidth(settings.plugins.levelpcb.probeWidth());
            self.probeHeight(settings.plugins.levelpcb.probeHeight());
            self.pointsX(settings.plugins.levelpcb.pointsX());
            self.pointsY(settings.plugins.levelpcb.pointsY());
        }

        self.onDataUpdaterPluginMessage = function(plugin, message) {
            if (plugin != 'levelpcb') return;

            if (message.status) {
                self.probeStatus(message.status);
            }
            else if (message.point) {
                console.log(message.point);
                factX = (size - padding * 2) / parseFloat(self.probeWidth());
                factY = (size - padding * 2) / parseFloat(self.probeHeight());
                ctx.fillText(message.point.z, message.point.x * factX + padding, message.point.y * factY + padding);
            }
        }

        self.sendJSON = function(content) {
            $.ajax({
                url: API_BASEURL + 'plugin/levelpcb',
                type: 'POST',
                dataType: 'json',
                data: JSON.stringify(content),
                contentType: 'application/json; charset=UTF-8'
            });
        }
    }

    OCTOPRINT_VIEWMODELS.push([
        LevelPCBViewModel,
        ['settingsViewModel'],
        ['#tab_plugin_levelpcb']
    ]);
});