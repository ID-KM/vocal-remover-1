import os
import uuid
import subprocess
import shutil
import json
from flask import Flask, render_template, request, jsonify, send_from_directory, Response

app = Flask(__name__)

# Configuration
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'output'
ALLOWED_EXTENSIONS = {'mp3', 'mp4'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER

# Ensure directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/process', methods=['POST'])
def process_media():
    session_id = str(uuid.uuid4())
    session_path = os.path.join(app.config['UPLOAD_FOLDER'], session_id)
    output_session_path = os.path.join(app.config['OUTPUT_FOLDER'], session_id)
    
    os.makedirs(session_path, exist_ok=True)
    os.makedirs(output_session_path, exist_ok=True)

    # --- Step 1: Acquire Audio Track (within request context) ---
    input_path = None
    original_ext = None
    url = None

    file = request.files.get('file')

    # Prioritize file upload
    if file and file.filename != '' :
        if allowed_file(file.filename):
            original_ext = file.filename.rsplit('.', 1)[1].lower()
            input_path = os.path.join(session_path, f'original.{original_ext}')
            file.save(input_path) # Save the file immediately
        else:
            # Invalid file type, let the generator handle the error message
            pass 
    # If no file, check for URL
    elif request.form.get('url'):
        url = request.form.get('url')

    # --- End of request context work ---

    def generator(start_input_path, start_original_ext, url_string):
        # This generator now receives paths and strings, not request objects
        input_path = start_input_path
        original_ext = start_original_ext

        try:
            yield 'data: {"status": "starting", "message": "بدء المعالجة..."}\n\n'

            if input_path:
                 yield 'data: {"status": "uploading", "message": "تم رفع الملف بنجاح"}\n\n'
            elif url_string:
                yield 'data: {"status": "downloading", "message": "جاري تحميل الفيديو من الرابط..."}\n\n'
                yt_output_template = os.path.join(session_path, 'original.%(ext)s')
                yt_command = ['yt-dlp', '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best', url_string, '-o', yt_output_template]
                
                try:
                    subprocess.run(yt_command, check=True, capture_output=True, text=True)
                except subprocess.CalledProcessError as e:
                    print("--- YOUTUBE-DL ERROR ---")
                    print(e.stderr)
                    print("------------------------")
                    yield f'data: {json.dumps({"status": "error", "message": f"فشل التحميل من الرابط: {e.stderr}"})}\n\n'
                    return

                downloaded_files = [f for f in os.listdir(session_path) if f.startswith('original')]
                if not downloaded_files:
                    yield 'data: {"status": "error", "message": "Failed to download from URL."}\n\n'
                    return
                
                input_path = os.path.join(session_path, downloaded_files[0])
                original_ext = input_path.rsplit('.', 1)[1].lower()
            else:
                yield 'data: {"status": "error", "message": "Invalid request: No file or URL provided"}\n\n'
                return

            # Step 2: Standardize to WAV
            yield 'data: {"status": "converting", "message": "جاري تحويل الصيغة إلى WAV..."}\n\n'
            
            shutil.copy(input_path, output_session_path)
            response_data = {
                'original_path': f'/output/{session_id}/{os.path.basename(input_path)}'
            }

            temp_audio_wav = os.path.join(session_path, 'temp_audio.wav')
            ffmpeg_command = ['ffmpeg', '-i', input_path, '-vn', '-acodec', 'pcm_s16le', '-ar', '44100', '-ac', '2', temp_audio_wav]
            try:
                subprocess.run(ffmpeg_command, check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as e:
                print("--- FFMPEG (WAV) ERROR ---")
                print(e.stderr)
                print("--------------------------")
                yield f'data: {json.dumps({"status": "error", "message": f"فشل تحويل الملف إلى WAV: {e.stderr}"})}\n\n'
                return

            # Step 3: Core Vocal Isolation with Demucs
            yield 'data: {"status": "separating", "message": "جاري عزل الصوت... هذه الخطوة قد تستغرق وقتاً طويلاً."}\n\n'
            demucs_executable = shutil.which('demucs')
            if not demucs_executable:
                yield 'data: {"status": "error", "message": "demucs executable not found in PATH."}\n\n'
                return

            demucs_command = [
                demucs_executable,
                '-o', session_path,
                '--two-stems', 'vocals',
                temp_audio_wav
            ]
            try:
                subprocess.run(demucs_command, check=True, capture_output=True, text=True)
                print("--- LISTING FILES AFTER DEMUCS ---")
                list_command = ['ls', '-lR', session_path]
                list_result = subprocess.run(list_command, capture_output=True, text=True)
                print(list_result.stdout)
                print("----------------------------------")
            except subprocess.CalledProcessError as e:
                print("--- DEMUCS ERROR ---")
                print(e.stderr)
                print("--------------------")
                yield f'data: {json.dumps({"status": "error", "message": f"فشل عزل الصوت: {e.stderr}"})}\n\n'
                return
            
            model_name = 'htdemucs'
            vocals_path = os.path.join(session_path, model_name, 'temp_audio', 'vocals.wav')
            if not os.path.exists(vocals_path):
                # Fallback for different model names
                separated_dirs = [d for d in os.listdir(session_path) if os.path.isdir(os.path.join(session_path, d))]
                for s_dir in separated_dirs:
                    potential_path = os.path.join(session_path, s_dir, 'temp_audio', 'vocals.wav')
                    if os.path.exists(potential_path):
                        vocals_path = potential_path
                        break
            if not os.path.exists(vocals_path):
                yield 'data: {"status": "error", "message": "Could not find vocals.wav after processing."}\n\n'
                return

            # Step 4: Generate Final Output Files
            yield 'data: {"status": "encoding", "message": "جاري إنشاء الملفات النهائية..."}\n\n'
            
            output_mp3_path = os.path.join(output_session_path, 'output.mp3')
            ffmpeg_mp3_command = ['ffmpeg', '-i', vocals_path, '-codec:a', 'libmp3lame', '-qscale:a', '2', output_mp3_path]
            try:
                subprocess.run(ffmpeg_mp3_command, check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as e:
                print("--- FFMPEG (MP3) ERROR ---")
                print(e.stderr)
                print("--------------------------")
                yield f'data: {json.dumps({"status": "error", "message": f"فشل إنشاء ملف MP3: {e.stderr}"})}\n\n'
                return
            response_data['mp3_path'] = f'/output/{session_id}/output.mp3'

            if original_ext == 'mp4':
                output_mp4_path = os.path.join(output_session_path, 'output.mp4')
                # --- START: MODIFIED CODE ---
                ffmpeg_mp4_command = [
                    'ffmpeg',
                    '-i', input_path,      # Input 0: Original video
                    '-i', vocals_path,     # Input 1: Separated vocals (WAV)
                    '-c:v', 'copy',        # Copy video stream without re-encoding
                    '-c:a', 'aac',         # Encode audio to AAC
                    '-b:a', '192k',        # Set audio bitrate to 192kbps
                    '-map', '0:v:0',       # Select video from Input 0
                    '-map', '1:a:0',       # Select audio from Input 1
                    '-shortest',           # Finish encoding when the shortest input ends
                    output_mp4_path
                ]
                # --- END: MODIFIED CODE ---
                try:
                    subprocess.run(ffmpeg_mp4_command, check=True, capture_output=True, text=True)
                except subprocess.CalledProcessError as e:
                    print("--- FFMPEG (MP4) ERROR ---")
                    print(e.stderr)
                    print("--------------------------")
                    yield f'data: {json.dumps({"status": "error", "message": f"فشل دمج الفيديو مع الصوت الجديد: {e.stderr}"})}\n\n'
                    return
                response_data['mp4_path'] = f'/output/{session_id}/output.mp4'

            response_data['message'] = 'اكتملت المعالجة بنجاح!'
            yield f'data: {json.dumps({"status": "done", "data": response_data})}\n\n'

        except Exception as e:
            # Generic error for unexpected issues
            print(f"--- GENERIC EXCEPTION CAUGHT ---")
            import traceback
            traceback.print_exc()
            print(f"--------------------------------")
            yield f'data: {json.dumps({"status": "error", "message": f"حدث خطأ غير متوقع: {str(e)}"})}\n\n'
        finally:
            # Cleanup the temporary session directory
            if os.path.exists(session_path):
                shutil.rmtree(session_path)

    return Response(generator(input_path, original_ext, url), mimetype='text/event-stream')

@app.route('/output/<session_id>/<filename>')
def send_output_file(session_id, filename):
    directory = os.path.join(app.config['OUTPUT_FOLDER'], session_id)
    return send_from_directory(directory, filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
