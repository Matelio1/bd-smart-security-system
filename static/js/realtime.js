document.addEventListener('DOMContentLoaded', function () {
    const statusBadge = document.getElementById('status-badge');
    const streamStatus = document.getElementById('stream-status');
    const liveStream = document.getElementById('live-stream');
    const reloadStreamBtn = document.getElementById('reload-stream-btn');
    const refreshBtn = document.getElementById('refresh-btn');
    const framesContainer = document.getElementById('frames-container');
    const loadingFrames = document.getElementById('loading-frames');
    const cameraSelect = document.getElementById('camera-select');

    const modal = document.getElementById('frame-modal');
    const modalImg = document.getElementById('frame-modal-image');
    const modalInfo = document.getElementById('frame-modal-info');
    const modalClose = document.querySelector('.frame-modal-close');
    const modalCloseBtn = document.getElementById('modal-close-btn');

    let currentCameraIndex = null; // Will be set after camera list loads

    window.handleStreamError = function () {
        console.error("Live stream error detected.");
        streamStatus.innerHTML = '<p class="text-danger">Error loading live stream. Is the analyzer running on the correct camera?</p>';
    };

    function updateAllCamerasStatus() {
        fetch("/api/analyzer/status?all=true")
            .then((res) => res.json())
            .then((data) => {
                const statusContainer = document.getElementById("all-cameras-status");
                statusContainer.innerHTML = "";

                if (data.cameras && Object.keys(data.cameras).length > 0) {
                    Object.entries(data.cameras).forEach(([camIdx, status]) => {
                        const isActive = status.status === "active";
                        const cameraCol = document.createElement("div");
                        cameraCol.className = "col-md-4 mb-3";
                        cameraCol.innerHTML = `
                            <div class="card ${isActive ? "border-success" : "border-danger"}">
                                <div class="card-header">
                                    Camera ${camIdx}
                                    <span class="badge bg-${isActive ? "success" : "danger"} float-end">
                                        ${isActive ? "Active" : "Inactive"}
                                    </span>
                                </div>
                                <div class="card-body">
                                    <p>Frames: ${status.frame_count || 0}</p>
                                    <button class="btn btn-sm btn-primary camera-view-btn" 
                                       data-camera-index="${camIdx}">View Stream</button>
                                </div>
                            </div>
                        `;
                        statusContainer.appendChild(cameraCol);
                    });

                    document.querySelectorAll(".camera-view-btn").forEach((btn) => {
                        btn.addEventListener("click", () => {
                            const camIdx = btn.getAttribute("data-camera-index");
                            switchCamera(camIdx);
                        });
                    });
                } else {
                    statusContainer.innerHTML =
                        '<p class="text-muted">No camera analyzers are currently running.</p>';
                }
            })
            .catch((err) => {
                console.error("Error fetching all camera status:", err);
                document.getElementById("all-cameras-status").innerHTML =
                    '<p class="text-danger">Error retrieving camera status.</p>';
            });
    }

    function updateStatus() {
        return fetch('/api/analyzer/status?camera_index=' + currentCameraIndex)
            .then(res => {
                if (!res.ok) {
                    throw new Error(`Status request failed: ${res.status}`);
                }
                return res.json();
            })
            .then(data => {
                if (data.status === 'active') {
                    statusBadge.className = 'badge bg-success';
                    streamStatus.innerHTML = `<p class="text-success">Analyzer active</p>
                        <p><small>Camera Index: ${data.camera_index ?? 'N/A'} | Frames Processed: ${data.frame_count ?? 0}</small></p>`;

                    // Ensure stream source is correct if status is active
                    const expectedStreamSrc = `/api/stream?camera_index=${data.camera_index}&t=${Date.now()}`;
                    if (liveStream.style.display === 'none' || !liveStream.src.includes(`/api/stream?camera_index=${data.camera_index}`)) {
                        liveStream.src = expectedStreamSrc;
                        liveStream.style.display = 'block';
                    }

                    // Update the camera select to match the active camera
                    if (data.camera_index !== null && cameraSelect.value != data.camera_index) {
                        cameraSelect.value = data.camera_index;
                        currentCameraIndex = parseInt(data.camera_index, 10);
                    }
                } else {
                    statusBadge.className = 'badge bg-danger';
                    statusBadge.textContent = 'Inactive';
                    liveStream.style.display = 'none';
                    return 'inactive';
                }
            })
            .catch((err) => {
                console.error("Error fetching status:", err);
                statusBadge.className = 'badge bg-warning';
                statusBadge.textContent = 'Error';
                streamStatus.innerHTML = '<p class="text-danger">Error fetching status from server</p>';
                liveStream.style.display = 'none';
                return 'error';
            });
    }

    function loadFrames() {
        loadingFrames.style.display = 'block';
        framesContainer.innerHTML = '';

        const cameraParam = document.getElementById('show-all-cameras').checked ? -1 : currentCameraIndex;

        fetch(`/api/analyzer/frames?limit=30&camera_index=${cameraParam}`)
            .then(res => {
                if (!res.ok) {
                    throw new Error(`Frame request failed: ${res.status}`);
                }
                return res.json();
            })
            .then(data => {
                loadingFrames.style.display = 'none';
                if (data.status === 'success') {
                    if (data.frames.length === 0) {
                        framesContainer.innerHTML = `<p class="text-muted">No recent frames found ${data.all_cameras ? 'for any cameras' : `for camera ${data.camera_index}`}. (${data.source})</p>`;
                        return;
                    }

                    data.frames.forEach(frame => {
                        const frameItem = document.createElement('div');
                        frameItem.className = 'frame-item card mb-2';

                        let objectsHtml = '';
                        if (frame.objects && Array.isArray(frame.objects) && frame.objects.length > 0) {
                            objectsHtml = '<div class="mt-1">' + frame.objects.map(obj =>
                                `<span class="badge bg-secondary me-1">${obj}</span>`).join('') + '</div>';
                        }

                        const imagePath = frame.path || '/static/placeholder.png';
                        const cameraInfo = `Camera ${frame.camera_index}`;

                        frameItem.innerHTML = `
                            <img src="${imagePath}" class="card-img-top frame-thumb" alt="Frame ${frame.id || frame.filename || ''}">
                            <div class="card-body p-2">
                                <p class="card-text mb-1">
                                    <span class="badge bg-primary me-1">${cameraInfo}</span>
                                    <small class="text-muted">${frame.timestamp || 'No timestamp'} (Frame ${frame.frame_number ?? 'N/A'})</small>
                                </p>
                                ${objectsHtml}
                            </div>`;

                        frameItem.addEventListener('click', () => {
                            modalImg.src = imagePath;
                            modalInfo.innerHTML = `
                                <h5>Camera ${frame.camera_index} - Captured: ${frame.timestamp || 'Unknown'}</h5>
                                <p>Source: ${data.source}</p>
                                <p>Objects Detected: ${frame.objects && frame.objects.length > 0 ? '' : 'None'}</p>
                                ${objectsHtml}`;
                            modal.style.display = 'flex';
                        });
                        framesContainer.appendChild(frameItem);
                    });
                } else {
                    framesContainer.innerHTML = `<p class="text-danger">Error loading frames: ${data.message || 'Unknown error'}</p>`;
                }
            })
            .catch((err) => {
                loadingFrames.style.display = 'none';
                framesContainer.innerHTML = `<p class="text-danger">Error connecting to server to fetch frames.</p>`;
            });
    }

    function populateCameraSelect(restoreCameraIndex = null) {
        cameraSelect.innerHTML = '<option value="" disabled>Loading cameras...</option>';
        fetch('/api/cameras')
            .then(res => {
                if (!res.ok) { throw new Error(`Camera list request failed: ${res.status}`); }
                return res.json();
            })
            .then(data => {
                cameraSelect.innerHTML = '';

                if (data.status === 'success' && data.cameras && data.cameras.length > 0) {
                    data.cameras.forEach(camera => {
                        const option = document.createElement('option');
                        option.value = camera.index;
                        option.textContent = camera.name || `Camera ${camera.index}`;
                        cameraSelect.appendChild(option);
                    });

                    // Restore selection if possible
                    let toSelect = restoreCameraIndex;
                    if (toSelect === null || toSelect === undefined) {
                        // Try to use currentCameraIndex if valid
                        if (currentCameraIndex !== null && data.cameras.some(cam => cam.index == currentCameraIndex)) {
                            toSelect = currentCameraIndex;
                        } else {
                            toSelect = data.cameras[0].index;
                        }
                    }
                    cameraSelect.value = toSelect;
                    currentCameraIndex = parseInt(cameraSelect.value, 10);

                    updateStatus().then(statusResult => {
                        if (statusResult !== 'active') {
                            loadFrames();
                        }
                    });

                } else {
                    const option = document.createElement('option');
                    option.value = "";
                    option.textContent = "No cameras found";
                    option.disabled = true;
                    cameraSelect.appendChild(option);
                    currentCameraIndex = null;
                    framesContainer.innerHTML = '<p class="text-warning">No cameras detected by the server.</p>';
                }
            })
            .catch(err => {
                cameraSelect.innerHTML = '';
                const option = document.createElement('option');
                option.textContent = "Error loading cameras";
                option.disabled = true;
                cameraSelect.appendChild(option);
                currentCameraIndex = null;
                framesContainer.innerHTML = '<p class="text-danger">Failed to load camera list from server.</p>';
            })
            .finally(() => {
                cameraSelect.disabled = false;
            });
    }

    function updateStatusBadge(text, color) {
        statusBadge.className = 'badge bg-' + color;
        statusBadge.textContent = text;
    }
    function refreshFrames() {
        loadFrames();
    }

    function pollStatusAfterSwitch(requestedCameraIndex, maxSeconds = 30, pollIntervalMs = 1000) {
        let waited = 0;
        let poller = setInterval(() => {
            fetch('/api/analyzer/status?camera_index=' + requestedCameraIndex)
                .then(res => res.json())
                .then(data => {
                    if (data.status === 'active' && data.camera_index == requestedCameraIndex) {
                        updateStatusBadge('Active', 'success');
                        streamStatus.innerHTML = `<p class="text-success">Analyzer active on camera ${requestedCameraIndex}</p>`;
                        cameraSelect.value = requestedCameraIndex;
                        currentCameraIndex = parseInt(requestedCameraIndex, 10);
                        reloadStreamBtn.disabled = false;
                        cameraSelect.disabled = false;
                        refreshBtn.disabled = false;
                        const expectedStreamSrc = `/api/stream?camera_index=${requestedCameraIndex}&t=${Date.now()}`;
                        liveStream.src = expectedStreamSrc;
                        liveStream.style.display = 'block';
                        clearInterval(poller);
                        refreshFrames();
                    } else if (data.status === 'inactive') {
                        updateStatusBadge('Inactive', 'danger');
                        streamStatus.innerHTML = `<p class="text-danger">Analyzer inactive</p>`;
                    } else {
                        updateStatusBadge('Switching', 'warning');
                        streamStatus.innerHTML = `<p class="text-warning">Waiting for camera ${requestedCameraIndex} to become active...</p>`;
                    }
                })
                .catch(err => {
                    updateStatusBadge('Error', 'danger');
                    streamStatus.innerHTML = `<p class="text-danger">Error polling analyzer status</p>`;
                });
            waited += pollIntervalMs / 1000;
            if (waited >= maxSeconds) {
                clearInterval(poller);
                updateStatusBadge('Timeout', 'danger');
                streamStatus.innerHTML = `<p class="text-danger">Analyzer did not become active in time.</p>`;
                reloadStreamBtn.disabled = false;
                cameraSelect.disabled = false;
                refreshBtn.disabled = false;
            }
        }, pollIntervalMs);
    }

    function handleRestartResponse(data, requestedCameraIndex) {
        if (data.status === 'success' || data.status === 'pending') {
            updateStatusBadge('Switching', 'warning');
            streamStatus.innerHTML = `<p class="text-warning">Switching to camera ${requestedCameraIndex}...</p>`;
            pollStatusAfterSwitch(requestedCameraIndex, 30, 1000);
        } else {
            updateStatusBadge('Error', 'danger');
            streamStatus.innerHTML = `<p class="text-danger">${data.message || "Unknown error"}</p>`;
            reloadStreamBtn.disabled = false;
            cameraSelect.disabled = false;
            refreshBtn.disabled = false;
        }
    }

    function switchCamera(newCameraIndex) {
        newCameraIndex = parseInt(newCameraIndex, 10);
        if (isNaN(newCameraIndex)) {
            alert("Invalid camera index selected.");
            return;
        }
        if (newCameraIndex === currentCameraIndex) {
            return;
        }
        currentCameraIndex = newCameraIndex;
        reloadStreamBtn.disabled = true;
        cameraSelect.disabled = true;
        refreshBtn.disabled = true;
        updateStatusBadge('Switching', 'warning');
        streamStatus.innerHTML = `<p class="text-warning">Attempting to switch to camera ${newCameraIndex}...</p>`;
        liveStream.style.display = 'none';
        liveStream.src = "";
        loadingFrames.style.display = 'block';
        framesContainer.innerHTML = '';

        fetch('/api/analyzer/restart', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', },
            body: JSON.stringify({ camera_index: currentCameraIndex })
        })
        .then(res => res.json())
        .then(data => {
            handleRestartResponse(data, currentCameraIndex);
        })
        .catch(err => {
            updateStatusBadge('Error', 'danger');
            streamStatus.innerHTML = `<p class="text-danger">Failed to switch camera: ${err.message || "Unknown error"}</p>`;
            reloadStreamBtn.disabled = false;
            cameraSelect.disabled = false;
            refreshBtn.disabled = false;
        });
    }

document.getElementById('start-all-cameras-btn').addEventListener('click', function() {
    this.disabled = true;
    this.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Starting...';

    fetch('/api/analyzer/start-all', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            // Refresh dropdown and camera feeds
            populateCameraSelect();
            updateAllCamerasStatus();
            setTimeout(() => loadAllCameraFeeds(), 5000);
        } else {
            alert(`Error: ${data.message}`);
        }
    })
    .catch(err => {
        alert(`Error starting cameras: ${err.message}`);
    })
    .finally(() => {
        this.disabled = false;
        this.innerHTML = '<i class="fas fa-play me-1"></i> Start All Cameras';
    });
});

document.getElementById('stop-all-cameras-btn').addEventListener('click', function() {
    const btn = this;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Stopping...';

    fetch('/api/analyzer/stop-all', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            updateAllCamerasStatus();
            // Wait for camera feeds to reload, then update overlays
            loadAllCameraFeedsWithOfflineOverlay();
        } else {
            alert(`Error: ${data.message}`);
        }
    })
    .catch(err => {
        alert(`Error stopping cameras: ${err.message}`);
    })
    .finally(() => {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-stop me-1"></i> Stop All Cameras';
    });
});

// Helper function to reload feeds and mark overlays as offline
function loadAllCameraFeedsWithOfflineOverlay() {
    // Call your existing loadAllCameraFeeds, but after it's done, update overlays
    fetch('/api/cameras')
        .then(res => res.json())
        .then(data => {
            if (data.status === 'success' && data.cameras && data.cameras.length > 0) {
                // Rebuild the grid
                multiCameraGrid.innerHTML = '';
                data.cameras.forEach(camera => {
                    const cameraIdx = camera.index;
                    const cameraFeed = createCameraFeed(cameraIdx);
                    multiCameraGrid.appendChild(cameraFeed);
                    // Mark overlay as offline
                    const overlay = document.querySelector(`#camera-feed-${cameraIdx} .camera-overlay`);
                    if (overlay) {
                        overlay.innerHTML = `Camera ${cameraIdx} <span class="badge bg-danger">Offline</span>`;
                    }
                });
            }
        });
}

    cameraSelect.addEventListener('change', () => {
        switchCamera(cameraSelect.value);
    });

    reloadStreamBtn.addEventListener('click', () => {
        if (currentCameraIndex === null || currentCameraIndex === undefined) {
            alert("No camera is currently selected or active to restart.");
            return;
        }
        reloadStreamBtn.disabled = true;
        cameraSelect.disabled = true;
        refreshBtn.disabled = true;
        reloadStreamBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Restarting...';
        updateStatusBadge('Restarting', 'warning');
        streamStatus.innerHTML = `<p class="text-warning">Attempting to restart camera ${currentCameraIndex}...</p>`;
        liveStream.style.display = 'none';
        liveStream.src = "";

        fetch('/api/analyzer/restart', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ camera_index: currentCameraIndex })
        })
        .then(res => res.json())
        .then(data => {
            handleRestartResponse(data, currentCameraIndex);
        })
        .catch(err => {
            updateStatusBadge('Error', 'danger');
            streamStatus.innerHTML = `<p class="text-danger">Failed to restart stream: ${err.message || "Unknown error"}</p>`;
            reloadStreamBtn.disabled = false;
            cameraSelect.disabled = false;
            refreshBtn.disabled = false;
        })
        .finally(() => {
            reloadStreamBtn.innerHTML = 'Restart Stream';
        });
    });

    modalClose.addEventListener('click', () => modal.style.display = 'none');
    modalCloseBtn.addEventListener('click', () => modal.style.display = 'none');
    window.addEventListener('click', (e) => { if (e.target === modal) modal.style.display = 'none'; });

    refreshBtn.addEventListener('click', () => {
        refreshBtn.disabled = true;
        refreshBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
        // --- FIX: preserve selected camera index on refresh ---
        const selectedCamera = cameraSelect.value;
        updateStatus().then(() => {
            loadFrames();
            refreshBtn.disabled = false;
            refreshBtn.innerHTML = 'Refresh';
        });
    });

    // --- MULTI-CAMERA HANDLING --- //
    const multiCameraGrid = document.getElementById('multi-camera-grid');
    const camerasLoading = document.getElementById('cameras-loading');
    const refreshCamerasBtn = document.getElementById('refresh-cameras-btn');
    const checkStatusBtn = document.getElementById('check-status-btn');
    let activeCameraFeeds = {};

    function createCameraFeed(cameraIdx) {
        const cameraFeed = document.createElement('div');
        cameraFeed.className = 'camera-feed';
        cameraFeed.id = `camera-feed-${cameraIdx}`;
        const timestamp = Date.now();
        cameraFeed.innerHTML = `
            <img src="/api/camera-thumbnail/${cameraIdx}?t=${timestamp}" 
                 alt="Camera ${cameraIdx}" 
                 class="camera-thumbnail"
                 data-camera-index="${cameraIdx}">
            <div class="camera-overlay">Camera ${cameraIdx} <span class="badge bg-warning">Loading...</span></div>
            <div class="camera-controls">
                <button class="camera-restart-btn" title="Restart" onclick="restartCamera(${cameraIdx})">
                    <i class="fas fa-sync-alt"></i>
                </button>
                <button class="camera-view-btn" title="View Stream" onclick="viewCameraStream(${cameraIdx})">
                    <i class="fas fa-eye"></i>
                </button>
            </div>
        `;
        cameraFeed.addEventListener('click', function(e) {
            if (!e.target.closest('button')) {
                viewCameraStream(cameraIdx);
            }
        });
        return cameraFeed;
    }

    window.viewCameraStream = function(cameraIdx) {
        const streamModal = document.getElementById('stream-modal');
        const streamModalTitle = document.getElementById('stream-modal-title');
        const streamModalImg = document.getElementById('stream-modal-image');
        streamModalTitle.textContent = `Camera ${cameraIdx} Live Stream`;
        const timestamp = Date.now();
        streamModalImg.src = `/api/stream?camera_index=${cameraIdx}&t=${timestamp}`;
        const bootstrapModal = new bootstrap.Modal(streamModal);
        bootstrapModal.show();
        streamModal.dataset.cameraIndex = cameraIdx;
    };

    document.getElementById('stream-restart-btn').addEventListener('click', function() {
        const streamModal = document.getElementById('stream-modal');
        const cameraIdx = streamModal.dataset.cameraIndex;
        if (cameraIdx) {
            this.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Restarting...';
            this.disabled = true;
            restartCamera(cameraIdx, true);
            setTimeout(() => {
                this.innerHTML = '<i class="fas fa-sync-alt me-1"></i> Restart Stream';
                this.disabled = false;
            }, 5000);
        }
    });

    window.handleCameraThumbnailLoaded = function(cameraIdx) {
        const overlay = document.querySelector(`#camera-feed-${cameraIdx} .camera-overlay`);
        if (overlay) {
            overlay.innerHTML = `Camera ${cameraIdx} <span class="badge bg-success">Ready</span>`;
        }
        activeCameraFeeds[cameraIdx] = true;
        setTimeout(() => {
            refreshCameraThumbnail(cameraIdx);
        }, 10000);
    };

    window.handleCameraThumbnailError = function(cameraIdx) {
        const overlay = document.querySelector(`#camera-feed-${cameraIdx} .camera-overlay`);
        if (overlay) {
            overlay.innerHTML = `Camera ${cameraIdx} <span class="badge bg-danger">Offline</span>`;
        }
    };

    window.restartCamera = function(cameraIdx, isInModal = false) {
        const overlay = document.querySelector(`#camera-feed-${cameraIdx} .camera-overlay`);
        if (overlay) {
            overlay.innerHTML = `Camera ${cameraIdx} <span class="badge bg-warning">Restarting...</span>`;
        }
        fetch('/api/analyzer/restart', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ camera_index: cameraIdx })
        })
        .then(res => res.json())
        .then(data => {
            if (data.status === 'success' || data.status === 'pending') {
                setTimeout(() => {
                    refreshCameraThumbnail(cameraIdx);
                    if (isInModal) {
                        const streamModalImg = document.getElementById('stream-modal-image');
                        streamModalImg.src = `/api/stream?camera_index=${cameraIdx}&t=${Date.now()}`;
                    }
                }, 5000);
            } else {
                if (overlay) {
                    overlay.innerHTML = `Camera ${cameraIdx} <span class="badge bg-danger">Failed</span>`;
                }
            }
        })
        .catch(err => {
            if (overlay) {
                overlay.innerHTML = `Camera ${cameraIdx} <span class="badge bg-danger">Error</span>`;
            }
        });
    };

    function refreshCameraThumbnail(cameraIdx) {
        const img = document.querySelector(`#camera-feed-${cameraIdx} img.camera-thumbnail`);
        if (img) {
            const timestamp = Date.now();
            img.src = `/api/camera-thumbnail/${cameraIdx}?t=${timestamp}`;
            img.onload = function() { handleCameraThumbnailLoaded(cameraIdx); };
            img.onerror = function() { handleCameraThumbnailError(cameraIdx); };
        }
    }

    function loadAllCameraFeeds() {
        camerasLoading.style.display = 'block';
        multiCameraGrid.innerHTML = '';
        activeCameraFeeds = {};

        fetch('/api/cameras')
            .then(res => res.json())
            .then(data => {
                camerasLoading.style.display = 'none';
                if (data.status === 'success' && data.cameras && data.cameras.length > 0) {
                    return fetch('/api/analyzer/status?all=true')
                        .then(res => res.json())
                        .then(statusData => {
                            data.cameras.forEach(camera => {
                                const cameraIdx = camera.index;
                                const isActive = statusData.cameras &&
                                    statusData.cameras[cameraIdx] &&
                                    statusData.cameras[cameraIdx].status === 'active';
                                const cameraFeed = createCameraFeed(cameraIdx);
                                multiCameraGrid.appendChild(cameraFeed);
                                if (!isActive) {
                                    const overlay = document.querySelector(`#camera-feed-${cameraIdx} .camera-overlay`);
                                    if (overlay) {
                                        overlay.innerHTML = `Camera ${cameraIdx} <span class="badge bg-warning">Starting...</span>`;
                                    }
                                    fetch('/api/analyzer/restart', {
                                        method: 'POST',
                                        headers: { 'Content-Type': 'application/json' },
                                        body: JSON.stringify({ camera_index: cameraIdx })
                                    })
                                    .then(res => res.json())
                                    .then(startData => {
                                        setTimeout(() => refreshCameraThumbnail(cameraIdx), 5000);
                                    })
                                    .catch(err => {
                                        const overlay = document.querySelector(`#camera-feed-${cameraIdx} .camera-overlay`);
                                        if (overlay) {
                                            overlay.innerHTML = `Camera ${cameraIdx} <span class="badge bg-danger">Start Failed</span>`;
                                        }
                                    });
                                } else {
                                    const img = document.querySelector(`#camera-feed-${cameraIdx} img.camera-thumbnail`);
                                    if (img) {
                                        img.onload = function() { handleCameraThumbnailLoaded(cameraIdx); };
                                        img.onerror = function() { handleCameraThumbnailError(cameraIdx); };
                                    }
                                }
                            });
                        });
                } else {
                    multiCameraGrid.innerHTML = '<p class="text-center text-muted">No cameras found</p>';
                }
            })
            .catch(err => {
                camerasLoading.style.display = 'none';
                multiCameraGrid.innerHTML = '<p class="text-center text-danger">Error loading camera information</p>';
            });
    }

    function refreshAllThumbnails() {
        document.querySelectorAll('.camera-feed').forEach(feed => {
            const cameraIdx = feed.id.replace('camera-feed-', '');
            refreshCameraThumbnail(cameraIdx);
        });
    }

    refreshCamerasBtn.addEventListener('click', refreshAllThumbnails);
    checkStatusBtn.addEventListener('click', updateAllCamerasStatus);

    // --- Camera select and refresh logic with selection persistence ---
    cameraSelect.disabled = true;
    reloadStreamBtn.disabled = true;
    refreshBtn.disabled = true;

    // Add checkbox for showing all camera frames
    
    const showAllCamerasCheck = document.createElement('div');
    showAllCamerasCheck.className = 'form-check form-switch ms-2';
    showAllCamerasCheck.innerHTML = `
        <input class="form-check-input" type="checkbox" id="show-all-cameras">
        <label class="form-check-label" for="show-all-cameras">Show all cameras</label>
    `;
    const cameraSelectParent = cameraSelect.parentNode;
    cameraSelectParent.appendChild(showAllCamerasCheck);

    document.getElementById('show-all-cameras').addEventListener('change', function() {
        if (this.checked) {
            cameraSelect.disabled = true;
            refreshFrames();
        } else {
            cameraSelect.disabled = false;
            refreshFrames();
        }
    });

    // --- Initial Load Sequence ---
    // Try to restore last selected camera from localStorage if available
    let lastSelectedCamera = localStorage.getItem('selectedCameraIndex');
    if (lastSelectedCamera !== null) {
        lastSelectedCamera = parseInt(lastSelectedCamera, 10);
    }
    populateCameraSelect(lastSelectedCamera);

    updateAllCamerasStatus();

    setInterval(updateAllCamerasStatus, 30000);
    setInterval(refreshAllThumbnails, 60000);

    setTimeout(() => {
        updateStatus().then(() => {
            loadFrames();
            if (currentCameraIndex !== null) {
                reloadStreamBtn.disabled = false;
            } else {
                reloadStreamBtn.disabled = true;
            }
            refreshBtn.disabled = false;
        });
    }, 1500);

    loadAllCameraFeeds();

    // --- Persist camera selection ---
cameraSelect.addEventListener('change', () => {
    localStorage.setItem('selectedCameraIndex', cameraSelect.value);
    // Only update recent detections, do not restart analyzer/stream
    loadFrames();
});

    // Also persist on camera switch via other UI
    function persistCameraSelection(idx) {
        localStorage.setItem('selectedCameraIndex', idx);
    }
});