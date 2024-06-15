import os
import time
import tarfile
import logging
import json
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive
from datetime import datetime
from threading import Timer

# Load configuration
with open('config.json') as config_file:
    config = json.load(config_file)

FOLDER_PATH = config['folder_path']
LOG_FILE = config['log_file']
DRIVE_FOLDER_ID = config['google_drive_folder_id']

# Configure logging to log to both file and console
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler(LOG_FILE),
                              logging.StreamHandler()])

class Watcher:
    DIRECTORY_TO_WATCH = FOLDER_PATH

    def __init__(self):
        self.observer = Observer()
        self.event_handler = Handler()
        self.observer.schedule(self.event_handler, self.DIRECTORY_TO_WATCH, recursive=True)
    
    def run(self):
        self.observer.start()
        try:
            while True:
                time.sleep(5)
        except KeyboardInterrupt:
            self.observer.stop()
            logging.info("Observer stopped by user")

        self.observer.join()

class Handler(FileSystemEventHandler):
    def __init__(self):
        self.timer = None
        self.last_event_time = None

    def on_any_event(self, event):
        # Filter only modify, create, and delete events
        if event.event_type not in ('modified', 'created', 'deleted'):
            return
        if event.is_directory:
            return
        logging.info(f"Detected change: {event.event_type} - {event.src_path}")
        if self.timer:
            self.timer.cancel()
        self.timer = Timer(60.0, self.process)  # Increase wait time to 60 seconds
        self.timer.start()

    def process(self):
        # Create tar.gz backup
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            tar_filename = f"backup_{os.path.basename(FOLDER_PATH)}_{timestamp}.tar.gz"
            tar_filepath = os.path.join('/tmp', tar_filename)
            
            with tarfile.open(tar_filepath, "w:gz") as tar:
                tar.add(FOLDER_PATH, arcname=os.path.basename(FOLDER_PATH))
            
            logging.info(f"Created tar file: {tar_filepath}")
        except Exception as e:
            logging.error(f"Error creating tar file: {e}")
            return

        # Upload to Google Drive
        try:
            gauth = GoogleAuth()
            gauth.settings['save_credentials'] = True
            gauth.settings['save_credentials_backend'] = 'file'
            gauth.settings['save_credentials_file'] = 'credentials.json'
            gauth.LoadCredentialsFile("credentials.json")
            if gauth.credentials is None:
                logging.error("Credentials not found. Please check credentials.json.")
            elif gauth.access_token_expired:
                gauth.Refresh()  # Refresh them if expired
            else:
                gauth.Authorize()  # Initialize the saved creds

            gauth.SaveCredentialsFile("credentials.json")

            drive = GoogleDrive(gauth)

            gfile = drive.CreateFile({'title': tar_filename, 'parents': [{'id': DRIVE_FOLDER_ID}]})
            gfile.SetContentFile(tar_filepath)
            gfile.Upload()
            logging.info(f"Uploaded {tar_filename} to Google Drive")

            # Remove the file after successful upload
            os.remove(tar_filepath)
            logging.info(f"Removed local file: {tar_filepath}")
        except Exception as e:
            logging.error(f"Error uploading to Google Drive: {e}")

if __name__ == '__main__':
    w = Watcher()
    w.run()
