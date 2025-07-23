document.addEventListener("DOMContentLoaded", function () {
  const uploadZone = document.getElementById("uploadZone");
  const videoUpload = document.getElementById("videoUpload");
  const videoPreview = document.getElementById("videoPreview");
  const analyzeBtn = document.getElementById("analyzeBtn");
  const progressSection = document.getElementById("progressSection");
  const analysisProgress = document.getElementById("analysisProgress");
  const statusMessage = document.getElementById("statusMessage");
  const resultsSection = document.getElementById("resultsSection");
  const analysisSummary = document.getElementById("analysisSummary");
  const detectedObjects = document.getElementById("detectedObjects");
  const frameGallery = document.getElementById("frameGallery");
  const errorSection = document.getElementById("errorSection");
  const errorMessage = document.getElementById("errorMessage");
  const newAnalysisBtn = document.getElementById("newAnalysisBtn");

  let selectedFile = null;

  // Handle drag and drop events
  uploadZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    uploadZone.classList.add("highlight");
  });

  uploadZone.addEventListener("dragleave", () => {
    uploadZone.classList.remove("highlight");
  });

  uploadZone.addEventListener("drop", (e) => {
    e.preventDefault();
    uploadZone.classList.remove("highlight");

    if (
      e.dataTransfer.files.length > 0 &&
      e.dataTransfer.files[0].type.startsWith("video/")
    ) {
      handleFileSelection(e.dataTransfer.files[0]);
    } else {
      showError("Please select a valid video file.");
    }
  });

  // Handle click to upload
  uploadZone.addEventListener("click", () => {
    videoUpload.click();
  });

  videoUpload.addEventListener("change", () => {
    if (videoUpload.files.length > 0) {
      handleFileSelection(videoUpload.files[0]);
    }
  });

  function handleFileSelection(file) {
    selectedFile = file;

    // Show video preview
    videoPreview.src = URL.createObjectURL(file);
    videoPreview.style.display = "block";

    // Enable analyze button
    analyzeBtn.disabled = false;

    // Hide any previous errors
    errorSection.style.display = "none";
  }

  // Handle analyze button click
  analyzeBtn.addEventListener("click", () => {
    if (!selectedFile) {
      showError("Please select a video file first.");
      return;
    }

    // Show progress section
    progressSection.style.display = "block";

    // Hide results if they were shown before
    resultsSection.style.display = "none";

    // Create form data
    const formData = new FormData();
    formData.append("video", selectedFile);

    // Simulate progress updates (since we can't get real-time updates from the server easily)
    let progress = 0;
    const progressInterval = setInterval(() => {
      if (progress < 90) {
        progress += Math.random() * 5;
        updateProgress(Math.min(progress, 90));
      }
    }, 1000);

    // Send the request
    fetch("/analyze", {
      method: "POST",
      body: formData,
    })
      .then((response) => {
        clearInterval(progressInterval);
        return response.json();
      })
      .then((data) => {
        updateProgress(100);
        setTimeout(() => {
          if (data.status === "success") {
            displayResults(data);
          } else {
            showError(data.message || "Analysis failed with an unknown error.");
          }
        }, 500);
      })
      .catch((error) => {
        clearInterval(progressInterval);
        showError("An error occurred during analysis: " + error.message);
      });
  });

  // Reset for new analysis
  newAnalysisBtn.addEventListener("click", () => {
    videoPreview.style.display = "none";
    videoPreview.src = "";
    analyzeBtn.disabled = true;
    progressSection.style.display = "none";
    resultsSection.style.display = "none";
    errorSection.style.display = "none";
    selectedFile = null;
    videoUpload.value = "";
  });

  function updateProgress(value) {
    const percentage = Math.round(value);
    analysisProgress.style.width = `${percentage}%`;
    analysisProgress.textContent = `${percentage}%`;

    if (percentage < 20) {
      statusMessage.innerHTML =
        '<i class="fas fa-spinner fa-spin me-2"></i>Starting video processing...';
    } else if (percentage < 40) {
      statusMessage.innerHTML =
        '<i class="fas fa-spinner fa-spin me-2"></i>Extracting frames...';
    } else if (percentage < 60) {
      statusMessage.innerHTML =
        '<i class="fas fa-spinner fa-spin me-2"></i>Running object detection...';
    } else if (percentage < 80) {
      statusMessage.innerHTML =
        '<i class="fas fa-spinner fa-spin me-2"></i>Analyzing detected objects...';
    } else if (percentage < 100) {
      statusMessage.innerHTML =
        '<i class="fas fa-spinner fa-spin me-2"></i>Finalizing results...';
    } else {
      statusMessage.innerHTML =
        '<i class="fas fa-check-circle me-2"></i>Analysis complete!';
      statusMessage.className = "alert alert-success";
    }
  }

  function showError(message) {
    errorMessage.textContent = message;
    errorSection.style.display = "block";
    progressSection.style.display = "none";
  }

  function displayResults(data) {
    // Fetch additional data about the video analysis
    fetch(`/api/video/${data.video_id}/analysis`)
      .then((response) => response.json())
      .then((analysisData) => {
        // Display the analysis summary
        analysisSummary.textContent =
          analysisData.summary || "Analysis completed successfully.";

        // Display detected objects
        detectedObjects.innerHTML = "";
        if (analysisData.objects && analysisData.objects.length > 0) {
          analysisData.objects.forEach((obj) => {
            const objectBadge = document.createElement("span");
            objectBadge.className = "detected-object";
            objectBadge.innerHTML = `<i class="fas fa-tag me-1"></i>${obj.name} (${obj.count})`;
            detectedObjects.appendChild(objectBadge);
          });
        } else {
          detectedObjects.innerHTML = "<p>No objects detected.</p>";
        }

        // Display frames
        frameGallery.innerHTML = "";
        if (analysisData.frames && analysisData.frames.length > 0) {
          analysisData.frames.forEach((frame) => {
            const frameItem = document.createElement("div");
            frameItem.className = "frame-item";
            frameItem.innerHTML = `
                                    <img src="${frame.image_path}" alt="Frame ${
              frame.frame_number
            }">
                                    <div class="frame-info">
                                        Frame #${frame.frame_number}
                                        <div class="small text-muted">${frame.objects.join(
                                          ", "
                                        )}</div>
                                    </div>
                                `;
            frameGallery.appendChild(frameItem);
          });
        } else {
          frameGallery.innerHTML = "<p>No frames with activity available.</p>";
        }

        // Show results section
        resultsSection.style.display = "block";
        progressSection.style.display = "none";
      })
      .catch((error) => {
        // If we can't get detailed analysis, show basic success
        analysisSummary.textContent =
          "Analysis completed successfully. Video has been processed.";
        resultsSection.style.display = "block";
        progressSection.style.display = "none";
      });
  }
});
