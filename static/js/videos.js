document.addEventListener('DOMContentLoaded', function() {
    // Modal elements
    const modal = document.getElementById('frame-modal');
    const modalImg = document.getElementById('frame-modal-image');
    const modalInfo = document.getElementById('frame-modal-info');
    const modalClose = document.querySelector('.frame-modal-close');
    const modalCloseBtn = document.getElementById('modal-close-btn');
    
    // Close modal functions
    function closeModal() {
        modal.style.display = 'none';
    }
    
    modalClose.addEventListener('click', closeModal);
    modalCloseBtn.addEventListener('click', closeModal);
    
    // Close modal when clicking outside the modal content
    window.addEventListener('click', function(event) {
        if (event.target === modal) {
            closeModal();
        }
    });
    
    // Add click handlers to video headers
    const videoHeaders = document.querySelectorAll('.video-header');
    videoHeaders.forEach(header => {
        header.addEventListener('click', function() {
            const videoId = this.getAttribute('data-video-id');
            const content = document.getElementById(`video-content-${videoId}`);
            const icon = this.querySelector('.toggle-icon');
            
            // Toggle display
            if (content.style.display === 'block') {
                content.style.display = 'none';
                icon.classList.remove('fa-chevron-up');
                icon.classList.add('fa-chevron-down');
            } else {
                content.style.display = 'block';
                icon.classList.remove('fa-chevron-down');
                icon.classList.add('fa-chevron-up');
                
                // Get frames container
                const framesContainer = document.getElementById(`frames-${videoId}`);
                
                // Debug: Log what's actually in the container
                console.log(`Frames container for video ${videoId} content:`, framesContainer.innerHTML);
                
                // Check if the container has any frame items already
                const hasFrames = framesContainer.querySelector('.frame-item') !== null;
                console.log(`Container has frames: ${hasFrames}`);
                
                if (!hasFrames) {
                    console.log(`Loading frames for video ID: ${videoId}`);
                    // Force clear any potential content
                    framesContainer.innerHTML = '';
                    loadFramesForVideo(videoId);
                } else {
                    console.log(`Frames already loaded for video ID: ${videoId}`);
                }
            }
        });
    });
    
    function loadFramesForVideo(videoId) {
        const loadingElement = document.getElementById(`loading-${videoId}`);
        const framesContainer = document.getElementById(`frames-${videoId}`);
        const statusContainer = document.getElementById(`status-container-${videoId}`);
        const tagsContainer = document.getElementById(`tags-list-${videoId}`);
        
        loadingElement.style.display = 'block';
        statusContainer.innerHTML = ''; // Clear any previous status
        
        console.log(`Fetching frames data from API for video ID: ${videoId}`);
        
        fetch(`/api/video/${videoId}/frames`)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! Status: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                loadingElement.style.display = 'none';
                console.log(`Received ${data.frames ? data.frames.length : 0} frames for video ${videoId}`);
                
                if (data.frames && data.frames.length > 0) {
                    // Create a status message and add it to the status container
                    const statusMsg = document.createElement('div');
                    statusMsg.className = 'frame-status alert alert-info';
                    statusMsg.id = `status-${videoId}`;
                    statusMsg.innerHTML = `Loading ${data.frames.length} frames...`;
                    statusContainer.appendChild(statusMsg);
                    
                    // Generate object tags for filtering
                    generateObjectTags(videoId, data.frames);
                    
                    // Process frames in smaller batches to avoid browser freezing
                    processFramesInBatches(data.frames, framesContainer, statusMsg);
                } else {
                    framesContainer.innerHTML = '<p class="text-muted">No frames found for this video.</p>';
                    tagsContainer.innerHTML = '<p class="text-muted">No objects detected</p>';
                }
            })
            .catch(error => {
                console.error("Error loading frames:", error);
                loadingElement.style.display = 'none';
                statusContainer.innerHTML = `<div class="alert alert-danger">Error loading frames: ${error.message}</div>`;
                tagsContainer.innerHTML = '<p class="text-muted">Failed to load tags</p>';
            });
    }
    
    function generateObjectTags(videoId, frames) {
        // Get all unique object types across all frames
        const allObjects = {};
        frames.forEach(frame => {
            frame.objects.forEach(obj => {
                if (!allObjects[obj]) {
                    allObjects[obj] = 0;
                }
                allObjects[obj]++;
            });
        });
        
        // Sort objects by count (most frequent first)
        const sortedObjects = Object.entries(allObjects)
            .sort((a, b) => b[1] - a[1])
            .map(entry => ({ name: entry[0], count: entry[1] }));
        
        const tagsContainer = document.getElementById(`tags-list-${videoId}`);
        const filterStats = document.getElementById(`filter-stats-${videoId}`);
        tagsContainer.innerHTML = '';
        
        // Add "All" tag first
        const allTag = document.createElement('span');
        allTag.className = 'object-tag active';
        allTag.dataset.object = 'all';
        allTag.innerHTML = `All <span class="badge">${frames.length}</span>`;
        tagsContainer.appendChild(allTag);
        
        // Add individual object tags
        sortedObjects.forEach(obj => {
            const tag = document.createElement('span');
            tag.className = 'object-tag';
            tag.dataset.object = obj.name;
            tag.innerHTML = `${obj.name} <span class="badge">${obj.count}</span>`;
            tagsContainer.appendChild(tag);
        });
        
        // Update filter stats
        filterStats.textContent = `Showing all ${frames.length} frames`;
        
        // Add click handlers to tags
        document.querySelectorAll(`#tags-list-${videoId} .object-tag`).forEach(tag => {
            tag.addEventListener('click', function() {
                filterFramesByObject(videoId, this.dataset.object);
            });
        });
    }
    
    function filterFramesByObject(videoId, objectType) {
        const framesContainer = document.getElementById(`frames-${videoId}`);
        const allFrameItems = framesContainer.querySelectorAll('.frame-item');
        const filterStats = document.getElementById(`filter-stats-${videoId}`);
        const allTags = document.querySelectorAll(`#tags-list-${videoId} .object-tag`);
        
        // Update active tag
        allTags.forEach(tag => {
            if (tag.dataset.object === objectType) {
                tag.classList.add('active');
            } else {
                tag.classList.remove('active');
            }
        });
        
        if (objectType === 'all') {
            // Show all frames
            allFrameItems.forEach(frame => {
                frame.classList.remove('filtered');
            });
            filterStats.textContent = `Showing all ${allFrameItems.length} frames`;
        } else {
            // Show only frames with the selected object
            let visibleCount = 0;
            
            allFrameItems.forEach(frame => {
                const frameObjects = frame.dataset.objects ? frame.dataset.objects.split(',') : [];
                if (frameObjects.includes(objectType)) {
                    frame.classList.remove('filtered');
                    visibleCount++;
                } else {
                    frame.classList.add('filtered');
                }
            });
            
            filterStats.textContent = `Showing ${visibleCount} frames with "${objectType}" (${Math.round((visibleCount/allFrameItems.length)*100)}%)`;
        }
    }
    
    function processFramesInBatches(frames, container, statusElement, batchSize = 10) {
        let processed = 0;
        const totalFrames = frames.length;
        
        function processNextBatch() {
            const batch = frames.slice(processed, processed + batchSize);
            
            batch.forEach(frame => {
                const frameItem = document.createElement('div');
                frameItem.className = 'frame-item';
                // Store the objects in a data attribute for filtering
                frameItem.dataset.objects = frame.objects.join(',');
                
                // Object tags
                const objectTags = frame.objects.map(obj => 
                    `<span class="detected-object"><i class="fas fa-tag me-1"></i>${obj}</span>`
                ).join(' ');
                
                // Use the API endpoint image path directly
                const imageSrc = frame.image_path;
                
                frameItem.innerHTML = `
                    <img src="${imageSrc}" alt="Frame ${frame.frame_number}" 
                        onerror="this.onerror=null; this.src='/static/images/image-not-found.png'; console.error('Failed to load image for frame ${frame.id}');"
                        loading="lazy">
                    <div class="frame-info">
                        <strong>Frame #${frame.frame_number}</strong>
                        <div class="mt-1">${objectTags || 'No objects'}</div>
                    </div>
                `;
                
                // Add click event to open modal
                frameItem.addEventListener('click', function() {
                    modalImg.src = imageSrc;
                    modalInfo.innerHTML = `
                        <h5>Frame #${frame.frame_number}</h5>
                        <div class="mt-2">${objectTags || 'No objects detected'}</div>
                    `;
                    modal.style.display = 'flex';
                });
                
                container.appendChild(frameItem);
            });
            
            processed += batch.length;
            
            // Update status
            statusElement.innerHTML = `Loaded ${processed} of ${totalFrames} frames...`;
            
            // Process next batch or finish
            if (processed < totalFrames) {
                // Use setTimeout to avoid blocking the UI
                setTimeout(processNextBatch, 50);
            } else {
                // All frames processed
                statusElement.innerHTML = `All ${totalFrames} frames loaded successfully.`;
                statusElement.className = 'frame-status alert alert-success';
                
                // Hide status after 3 seconds
                setTimeout(() => {
                    statusElement.style.display = 'none';
                }, 3000);
            }
        }
        
        // Start processing
        processNextBatch();
    }
    
    // Manually check and preload frames for any video sections that might already be open
    document.querySelectorAll('.video-content').forEach(content => {
        if (content.style.display === 'block') {
            const videoId = content.id.split('-').pop();
            const framesContainer = document.getElementById(`frames-${videoId}`);
            
            // Check if frames are already loaded
            if (!framesContainer.querySelector('.frame-item')) {
                console.log(`Found open video section ${videoId}. Loading frames...`);
                loadFramesForVideo(videoId);
            }
        }
    });
});
