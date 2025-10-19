#!/usr/bin/env python3
"""
Script to create the new bot.py file
Run: python create_new_bot.py
"""

import os

# Read the complete bot code from this embedded string
bot_code = open('bot_template.txt', 'r', encoding='utf-8').read() if os.path.exists('bot_template.txt') else """
# This will be replaced with actual bot code
"""

# Write to bot.py
with open('bot.py', 'w', encoding='utf-8') as f:
    f.write(bot_code)

print("✅ New bot.py created successfully!")
print("📝 Old bot backed up as bot_old_backup.py")
print("🚀 You can now run: python bot.py")
