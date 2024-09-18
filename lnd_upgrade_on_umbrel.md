# HOW To Upgrade to the Latest Version of LND Without Waiting for UMBREL

Follow these steps:

1. **Backup the `docker-compose.yml` File**  
   Navigate to your `/home/<user>/umbrel/app-data/lightning/` folder and backup the `docker-compose.yml` file by running the command:
   ```bash
   sudo cp docker-compose.yml docker-compose.bck
2. Open the `docker-compose.yml` file for editing by running:
   ```bash
   sudo nano docker-compose.yml
3. Locate line `45` and change its content to:
   ```bash
   image: lightninglabs/lnd:v0.18.3-beta.rc3@sha256:42cf149d859b16fdc37d17f1944d6d67ee9c9a8fcd1d34d940f0f0b30b17b2be
4. Press `CTRL+X`, then press `Y` to save the changes, and hit `Enter` to exit the editor.
5. Restart your LND by running:
   ```bash
   /home/<user>/umbrel/scripts/app restart lightning

**Attention:** Replace `<user>` with your actual username.

**Important:** This procedure has been tested with more than five different LND nodes and has proven to work. However, if you are not confident, please do not proceed and wait for Umbrel to release the update.
