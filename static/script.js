document.addEventListener('DOMContentLoaded', () => {
    // Sections
    const inputSection = document.getElementById('input-section');
    const processingSection = document.getElementById('processing-section');
    const resultsSection = document.getElementById('results-section');
    const errorSection = document.getElementById('error-section');

    // Forms and Inputs
    const form = document.getElementById('process-form');
    const fileInput = document.getElementById('file-input');
    const urlInput = document.getElementById('url-input');
    const submitBtn = document.getElementById('submit-btn');

    // Drag & Drop
    const dropZone = document.getElementById('drop-zone');
    const browseBtn = document.getElementById('browse-btn');

    // Progress
    const progressBarInner = document.getElementById('progress-bar-inner');
    const progressText = document.getElementById('progress-text');

    // Results
    const originalAudio = document.getElementById('original-audio');
    const vocalsAudio = document.getElementById('vocals-audio');
    const downloadOptions = document.getElementById('download-options');
    const resetBtn = document.getElementById('reset-btn');

    // Error
    const errorMessage = document.getElementById('error-message');
    const errorResetBtn = document.getElementById('error-reset-btn');

    let selectedFile = null;

    // --- UI State Management ---
    function showSection(section) {
        [inputSection, processingSection, resultsSection, errorSection].forEach(s => s.classList.add('hidden'));
        section.classList.remove('hidden');
    }

    function resetUI() {
        form.reset();
        selectedFile = null;
        submitBtn.disabled = true;
        dropZone.querySelector('p').textContent = 'اسحب وأفلت ملفًا صوتيًا أو فيديو هنا';
        showSection(inputSection);
    }

    function updateSubmitButtonState() {
        submitBtn.disabled = !selectedFile && !urlInput.value.trim();
    }

    // --- Event Listeners ---

    // Drag and Drop
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('drag-over');
    });

    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('drag-over');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('drag-over');
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleFile(files[0]);
        }
    });

    // Browse Button
    browseBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) {
            handleFile(fileInput.files[0]);
        }
    });

    // URL Input
    urlInput.addEventListener('input', () => {
        if (urlInput.value.trim()) {
            selectedFile = null;
            dropZone.querySelector('p').textContent = 'اسحب وأفلت ملفًا صوتيًا أو فيديو هنا';
        }
        updateSubmitButtonState();
    });

    // Form Submission
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        showSection(processingSection);
        updateProgress(0, 'بدء المعالجة...');

        const formData = new FormData(form);

        try {
            const response = await fetch('/api/process', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'حدث خطأ غير معروف في الخادم');
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;

                const chunk = decoder.decode(value);
                const lines = chunk.split('\n').filter(line => line.trim().startsWith('data:'));

                for (const line of lines) {
                    const jsonString = line.replace('data: ', '');
                    const data = JSON.parse(jsonString);

                    let percentage = 0;
                    switch (data.status) {
                        case 'starting': percentage = 5; break;
                        case 'uploading': percentage = 15; break;
                        case 'downloading': percentage = 20; break;
                        case 'converting': percentage = 50; break;
                        case 'separating': percentage = 70; break;
                        case 'encoding': percentage = 95; break;
                        case 'done': percentage = 100; break;
                    }
                    updateProgress(percentage, data.message);

                    if (data.status === 'done') {
                        displayResults(data.data);
                    } else if (data.status === 'error') {
                        displayError(data.message);
                        return; // Stop processing on error
                    }
                }
            }

        } catch (error) {
            displayError(error.message);
        }
    });

    // Reset Buttons
    resetBtn.addEventListener('click', resetUI);
    errorResetBtn.addEventListener('click', resetUI);

    // --- Helper Functions ---

    function handleFile(file) {
        selectedFile = file;
        urlInput.value = '';
        dropZone.querySelector('p').textContent = `الملف المحدد: ${file.name}`;
        updateSubmitButtonState();
    }

    function updateProgress(percentage, text) {
        progressBarInner.style.width = `${percentage}%`;
        progressText.textContent = text;
    }

    function displayResults(result) {
        showSection(resultsSection);
        console.log(result);

        // Show and set the original audio player
        if (result.original_path) {
            originalAudio.src = result.original_path;
            originalAudio.parentElement.classList.remove('hidden');
        } else {
            originalAudio.parentElement.classList.add('hidden');
        }

        vocalsAudio.src = result.mp3_path; // Assuming mp3_path is always present

        downloadOptions.innerHTML = ''; // Clear previous buttons
        if (result.mp3_path) {
            const mp3Link = document.createElement('a');
            mp3Link.href = result.mp3_path;
            mp3Link.textContent = 'تحميل MP3 (صوت فقط)';
            mp3Link.className = 'download-btn';
            mp3Link.download = 'vocals.mp3';
            downloadOptions.appendChild(mp3Link);
        }
        if (result.mp4_path) {
            const mp4Link = document.createElement('a');
            mp4Link.href = result.mp4_path;
            mp4Link.textContent = 'تحميل MP4 (فيديو)';
            mp4Link.className = 'download-btn';
            mp4Link.download = 'video_with_vocals.mp4';
            downloadOptions.appendChild(mp4Link);
        }
    }

    function displayError(message) {
        errorMessage.textContent = message;
        showSection(errorSection);
    }

    // Initial state
    resetUI();
});