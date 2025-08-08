import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread

# Configuration initiale du bot
intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Configuration des fichiers de données
TEMP_CHANNELS_FILE = "temp_channels.json"
USER_COUNTS_FILE = "user_counts.json"
GUILD_LANGUAGES_FILE = "guild_languages.json"
HOSTING_CHANNELS_FILE = "hosting_channels.json"

# Initialisation des structures de données
temp_channels = {}
user_channel_counts = {}
hosting_channels = {}
guild_languages = {}

# Constantes
MAX_CHANNELS_PER_USER = 3
CREATE_VOICE_CHANNEL_NAME = "➕ Créer Salon Vocal"
DEFAULT_DURATION = 60  # 60 minutes par défaut

# Serveur Flask pour keep-alive
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Discord de gestion de canaux temporaires en ligne!"

def run_flask():
    app.run(host='0.0.0.0', port=5000)

def keep_alive():
    Thread(target=run_flask).start()

# Fonctions de gestion des données
def load_data():
    global temp_channels, user_channel_counts, hosting_channels, guild_languages
    
    if os.path.exists(TEMP_CHANNELS_FILE):
        try:
            with open(TEMP_CHANNELS_FILE, 'r') as f:
                temp_channels = json.load(f)
                for channel_id, data in temp_channels.items():
                    data['expires_at'] = datetime.fromisoformat(data['expires_at'])
        except Exception as e:
            print(f"Erreur lors du chargement des canaux temporaires: {e}")
            temp_channels = {}
    
    if os.path.exists(USER_COUNTS_FILE):
        try:
            with open(USER_COUNTS_FILE, 'r') as f:
                user_channel_counts = json.load(f)
        except Exception as e:
            print(f"Erreur lors du chargement des compteurs utilisateurs: {e}")
            user_channel_counts = {}
    
    if os.path.exists(HOSTING_CHANNELS_FILE):
        try:
            with open(HOSTING_CHANNELS_FILE, 'r') as f:
                hosting_channels = json.load(f)
        except Exception as e:
            print(f"Erreur lors du chargement des canaux d'hébergement: {e}")
            hosting_channels = {}
    
    if os.path.exists(GUILD_LANGUAGES_FILE):
        try:
            with open(GUILD_LANGUAGES_FILE, 'r') as f:
                guild_languages = json.load(f)
        except Exception as e:
            print(f"Erreur lors du chargement des langues: {e}")
            guild_languages = {}

def save_data():
    try:
        with open(TEMP_CHANNELS_FILE, 'w') as f:
            temp_data = {}
            for channel_id, data in temp_channels.items():
                temp_data[channel_id] = {
                    'creator_id': data['creator_id'],
                    'guild_id': data['guild_id'],
                    'name': data['name'],
                    'expires_at': data['expires_at'].isoformat(),
                    'is_voice': data['is_voice']
                }
            json.dump(temp_data, f, indent=2)
        
        with open(USER_COUNTS_FILE, 'w') as f:
            json.dump(user_channel_counts, f, indent=2)
        
        with open(HOSTING_CHANNELS_FILE, 'w') as f:
            json.dump(hosting_channels, f, indent=2)
        
        with open(GUILD_LANGUAGES_FILE, 'w') as f:
            json.dump(guild_languages, f, indent=2)
    except Exception as e:
        print(f"Erreur lors de la sauvegarde des données: {e}")

# Système de traduction
TRANSLATIONS = {
    "fr": {
        "bot_connected": "✅ Bot connecté en tant que {0}",
        "channel_renamed": "✅ Salon renommé avec succès!\nAncien nom: {0}\nNouveau nom: {1}",
        "rename_failed": "❌ Échec du renommage du salon",
        "max_channels_reached": "❌ Limite de {0} salons atteinte ({1}/{2})",
        "welcome_temp_voice": "🔊 Bienvenue dans votre salon vocal temporaire!\nSuppression dans {0} minutes",
        "welcome_temp_text": "💬 Bienvenue dans votre salon textuel temporaire!\nSuppression dans {0} minutes",
        "channel_created": "✅ Salon créé: {0}\nExpire le: {1}",
        "temp_channel_expired": "⏰ Salon expiré supprimé: {0}",
        "no_permission_modify": "❌ Permission insuffisante",
        "min_duration": "❌ Durée minimale: 1 minute",
        "max_duration": "❌ Durée maximale: 43200 minutes (30 jours)",
        "invalid_channel_name": "❌ Nom invalide (1-100 caractères)",
        "temp_channel_only": "❌ Commande réservée aux salons temporaires",
        "host_creator_only": "❌ Seul le créateur peut faire cela",
        "language_set": "✅ Langue du serveur définie sur {0}",
        "language_invalid": "❌ Langue invalide. Langues disponibles: {0}"
    },
    "en": {
        "bot_connected": "✅ Bot connected as {0}",
        "channel_renamed": "✅ Channel renamed!\nOld name: {0}\nNew name: {1}",
        "rename_failed": "❌ Failed to rename channel",
        "max_channels_reached": "❌ Limit of {0} channels reached ({1}/{2})",
        "welcome_temp_voice": "🔊 Welcome to your temporary voice channel!\nWill be deleted in {0} minutes",
        "welcome_temp_text": "💬 Welcome to your temporary text channel!\nWill be deleted in {0} minutes",
        "channel_created": "✅ Channel created: {0}\nExpires at: {1}",
        "temp_channel_expired": "⏰ Expired channel deleted: {0}",
        "no_permission_modify": "❌ Missing permission to modify channel",
        "min_duration": "❌ Minimum duration: 1 minute",
        "max_duration": "❌ Maximum duration: 43200 minutes (30 days)",
        "invalid_channel_name": "❌ Invalid channel name (1-100 chars)",
        "temp_channel_only": "❌ Command only for temporary channels",
        "host_creator_only": "❌ Only the creator can do this",
        "language_set": "✅ Server language set to {0}",
        "language_invalid": "❌ Invalid language. Available: {0}"
    }
}

def get_guild_language(guild_id):
    return guild_languages.get(str(guild_id), "fr")

def set_guild_language(guild_id, language):
    if language in TRANSLATIONS:
        guild_languages[str(guild_id)] = language
        save_data()
        return True
    return False

def get_text(guild_id, key, *args):
    lang = get_guild_language(guild_id) if guild_id else "fr"
    return TRANSLATIONS.get(lang, {}).get(key, key).format(*args)

async def can_create_channel(user_id):
    return user_channel_counts.get(str(user_id), 0) < MAX_CHANNELS_PER_USER

async def create_temporary_channel(guild, creator, channel_name, duration, is_voice=True, category=None):
    if not await can_create_channel(creator.id):
        return False, get_text(guild.id, "max_channels_reached", MAX_CHANNELS_PER_USER, 
                               user_channel_counts.get(str(creator.id), 0), MAX_CHANNELS_PER_USER), None
    
    try:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False, connect=False),
            creator: discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True, manage_permissions=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True, manage_permissions=True)
        }

        if is_voice:
            channel = await guild.create_voice_channel(name=channel_name, overwrites=overwrites, category=category)
        else:
            channel = await guild.create_text_channel(name=channel_name, overwrites=overwrites, category=category)

        expires_at = datetime.now() + timedelta(minutes=duration)
        temp_channels[str(channel.id)] = {
            'creator_id': creator.id,
            'guild_id': guild.id,
            'name': channel.name,
            'expires_at': expires_at,
            'is_voice': is_voice
        }

        user_channel_counts[str(creator.id)] = user_channel_counts.get(str(creator.id), 0) + 1
        save_data()

        welcome_msg = get_text(guild.id, "welcome_temp_voice" if is_voice else "welcome_temp_text", duration)
        if not is_voice:
            await channel.send(welcome_msg)

        return True, get_text(guild.id, "channel_created", channel.mention, expires_at.strftime("%Y-%m-%d %H:%M")), channel

    except discord.Forbidden:
        return False, get_text(guild.id, "no_permission_modify"), None
    except Exception as e:
        return False, f"❌ Erreur: {str(e)}", None

async def delete_temporary_channel(channel_id):
    try:
        channel = bot.get_channel(int(channel_id))
        if channel:
            await channel.delete()
        
        if channel_id in temp_channels:
            creator_id = temp_channels[channel_id]['creator_id']
            user_channel_counts[str(creator_id)] = max(0, user_channel_counts.get(str(creator_id), 1) - 1)
            if user_channel_counts[str(creator_id)] == 0:
                del user_channel_counts[str(creator_id)]
            
            del temp_channels[channel_id]
            save_data()
        
        return True
    except Exception as e:
        print(f"Erreur suppression salon: {e}")
        return False

@tasks.loop(minutes=5)
async def cleanup_task():
    now = datetime.now()
    to_delete = [cid for cid, data in temp_channels.items() if data['expires_at'] < now]
    for channel_id in to_delete:
        await delete_temporary_channel(channel_id)
        print(get_text(None, "temp_channel_expired", channel_id))

# Commande pour changer la langue
@bot.tree.command(name="set_language", description="Définit la langue du serveur")
@app_commands.describe(langue="Code de langue (fr, en, es...)")
async def set_language(interaction: discord.Interaction, langue: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(get_text(interaction.guild.id, "no_permission_modify"), ephemeral=True)
        return
    if set_guild_language(interaction.guild.id, langue):
        await interaction.response.send_message(get_text(interaction.guild.id, "language_set", langue))
    else:
        await interaction.response.send_message(get_text(interaction.guild.id, "language_invalid", ", ".join(TRANSLATIONS.keys())), ephemeral=True)

# Événements
@bot.event
async def on_ready():
    print(get_text(None, "bot_connected", bot.user.name))
    load_data()
    try:
        synced = await bot.tree.sync()
        print(f"Commandes synchronisées: {len(synced)}")
    except Exception as e:
        print(f"Erreur synchronisation commandes: {e}")
    cleanup_task.start()

if __name__ == "__main__":
    keep_alive()
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("❌ Token Discord non trouvé dans les variables d'environnement!")
        exit(1)
    bot.run(token)
