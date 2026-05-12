"""Fix constructor signatures in channel classes to accept optional token parameter."""

# Fix telegram.py
with open(r'backend/src/ai_platform/channels/telegram.py', 'r', encoding='utf-8') as f:
    content = f.read()
content = content.replace(
    'def __init__(self):\n        self.settings = get_settings()\n        self.token = self.settings.TELEGRAM_BOT_TOKEN',
    'def __init__(self, token: str | None = None):\n        self.settings = get_settings()\n        self.token = token if token is not None else self.settings.TELEGRAM_BOT_TOKEN',
)
with open(r'backend/src/ai_platform/channels/telegram.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('telegram.py: token parameter added')

# Fix discord.py
with open(r'backend/src/ai_platform/channels/discord.py', 'r', encoding='utf-8') as f:
    content = f.read()
content = content.replace(
    'def __init__(self):\n        self.settings = get_settings()\n        self.token = self.settings.DISCORD_BOT_TOKEN',
    'def __init__(self, token: str | None = None):\n        self.settings = get_settings()\n        self.token = token if token is not None else self.settings.DISCORD_BOT_TOKEN',
)
with open(r'backend/src/ai_platform/channels/discord.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('discord.py: token parameter added')

# Fix whatsapp_channel.py
with open(r'backend/src/ai_platform/channels/whatsapp_channel.py', 'r', encoding='utf-8') as f:
    content = f.read()
content = content.replace(
    '    def __init__(self):',
    '    def __init__(self, token: str | None = None):',
)
with open(r'backend/src/ai_platform/channels/whatsapp_channel.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('whatsapp_channel.py: token parameter added')

# Fix base.py
with open(r'backend/src/ai_platform/channels/base.py', 'r', encoding='utf-8') as f:
    content = f.read()
# Remove ABC/abstractmethod from imports
content = content.replace('from abc import ABC, abstractmethod\n', '')
# Remove abstractmethod decorators
import re
content = re.sub(r'    @abstractmethod\n    async def send_message', '    async def send_message', content)
content = re.sub(r'    @abstractmethod\n    async def validate_webhook', '    async def validate_webhook', content)
content = re.sub(r'    @abstractmethod\n    async def extract_message', '    async def extract_message', content)
# Change class declaration
content = content.replace('class BaseChannel(ABC):', 'class BaseChannel:')
# Change channel: str to channel: str = ""
content = content.replace('    channel: str\n    _rate_limiter:', '    channel: str = ""\n    _rate_limiter:')
with open(r'backend/src/ai_platform/channels/base.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('base.py: removed ABC, abstractmethod, base class now instantiable')

print('\nAll source files fixed successfully.')
