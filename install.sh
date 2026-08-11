#!/bin/bash

echo "Installing Theos Compiler Bot..."

# Install system dependencies
sudo apt-get update
sudo apt-get install -y python3 python3-pip unrar p7zip-full

# Install Python dependencies
pip3 install -r requirements.txt

# Setup systemd service
sudo cp theos-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable theos-bot
sudo systemctl start theos-bot

echo "Installation complete!"
echo "Check status: sudo systemctl status theos-bot"
echo "View logs: sudo journalctl -u theos-bot -f"
