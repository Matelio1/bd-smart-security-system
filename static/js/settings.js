document.addEventListener('DOMContentLoaded', function() {
    // Object classes storage - Fix JSON serialization
    let objectClasses;
    try {
        objectClasses = {
            realtime: JSON.parse(document.getElementById('settings-data').dataset.realtimeClasses),
            video: JSON.parse(document.getElementById('settings-data').dataset.videoClasses)
        };
    } catch (e) {
        console.error("Error parsing JSON:", e);
        // Set defaults in case of error
        objectClasses = {
            realtime: ["person", "car", "truck", "motorcycle", "bicycle", "bus"],
            video: ["person", "car", "truck"]
        };
    }

    // Update confidence display as slider moves
    document.getElementById('realtime-confidence').addEventListener('input', function() {
        document.getElementById('realtime-confidence-value').textContent = this.value;
    });

    document.getElementById('video-confidence').addEventListener('input', function() {
        document.getElementById('video-confidence-value').textContent = this.value;
    });

    // Add object class
    window.addObjectClass = function(type) {
        const inputField = document.getElementById(`${type}-new-class`);
        const className = inputField.value.trim().toLowerCase();

        if (className && !objectClasses[type].includes(className)) {
            objectClasses[type].push(className);
            updateObjectClassDisplay(type);
            inputField.value = '';
        }
    };

    // Remove object class
    window.removeObjectClass = function(type, className) {
        const index = objectClasses[type].indexOf(className);
        if (index !== -1) {
            objectClasses[type].splice(index, 1);
            updateObjectClassDisplay(type);
        }
    };

    // Update object class display
    function updateObjectClassDisplay(type) {
        const container = document.getElementById(`${type}-classes`);
        container.innerHTML = '';

        objectClasses[type].forEach(className => {
            const element = document.createElement('div');
            element.className = 'object-class';
            element.innerHTML = `
                ${className}
                <button type="button" class="btn-close ms-2" aria-label="Remove" 
                        onclick="removeObjectClass('${type}', '${className}')"></button>
            `;
            container.appendChild(element);
        });
    }

    // Save settings
    window.saveSettings = function(type) {
        const settings = {};

        if (type === 'realtime') {
            settings.confidence = parseFloat(document.getElementById('realtime-confidence').value);
            settings.save_interval = parseInt(document.getElementById('realtime-save-interval').value);
            settings.frame_rate = parseFloat(document.getElementById('realtime-frame-rate').value);
            settings.include_classes = objectClasses.realtime;
        } else {
            settings.confidence = parseFloat(document.getElementById('video-confidence').value);
            settings.frame_interval = parseInt(document.getElementById('video-frame-interval').value);
            settings.min_objects = parseInt(document.getElementById('video-min-objects').value);
            settings.include_classes = objectClasses.video;
        }

        // Send settings to server
        fetch('/settings/update', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                type: type,
                settings: settings
            }),
        })
        .then(response => response.json())
        .then(data => {
            const statusMessage = document.getElementById('status-message');
            statusMessage.textContent = data.message;
            statusMessage.className = `status-message alert ${data.success ? 'alert-success' : 'alert-danger'}`;
            statusMessage.style.display = 'block';

            // Hide message after 3 seconds
            setTimeout(() => {
                statusMessage.style.display = 'none';
            }, 3000);
        })
        .catch(error => {
            console.error('Error saving settings:', error);
            const statusMessage = document.getElementById('status-message');
            statusMessage.textContent = 'Error saving settings. Please try again.';
            statusMessage.className = 'status-message alert alert-danger';
            statusMessage.style.display = 'block';
        });
    };

    // Initial rendering of object classes
    updateObjectClassDisplay('realtime');
    updateObjectClassDisplay('video');
});