# bot.py
"""
Bot Discord complet regroupant :
- Hébergement de "hosting channels" (texte / vocal)
- Création de canaux temporaires (texte ou vocal)
- Limite : maximum 3 canaux temporaires actifs par utilisateur
- Commandes slash et commandes préfixées (où utile)
- Langues / traductions (fr / en / ar)
- Keepalive minimal via Flask (utile pour Replit)
- Persistance JSON pour ne pas perdre les configs au redémarrage
- Gestion automatique de suppression de canaux vides
- Keepalive configurable par serveur (envoi périodique)
- Commandes d'administration : setup_hosting, remove_hosting, list_hosting, setup_keepalive, remove_keepalive, keepalive_status
- Commandes utilisateur : create_temp, delete_temp, list_temp, invite (pour inviter/ajouter un user), change_host
- Le code est volontairement détaillé et commenté.
"""

import discord
from discord.ext import commands, tasks
import discord.app_commands as app_commands
import asyncio
import json
import os
from threading import Thread
from flask import Flask
from typing import Optional, Dict, Any, List
import time
import traceback

# ---------------------------
# Configuration / constants
# ---------------------------
# TOKEN can be stored in environment variable DISCORD_TOKEN or in config.json file
DATA_FILE = "bot_data.json"  # persistence file
DEFAULT_TEMP_CATEGORY_ID = None  # si tu veux forcer une catégorie par défaut, mets l'ID ici, sinon None
KEEPALIVE_PORT = int(os.environ.get("KEEPALIVE_PORT", 8080))

# If present, a config.json can specify token and optionally guild id (not required)
CONFIG_FILE = "config.json"

# ---------------------------
# Flask keepalive (minimal)
# ---------------------------
app = Flask("keepalive_app")


@app.route("/")
def home():
    return "Bot is alive!"


def run_keepalive_server() -> None:
    """
    Démarre le serveur Flask sur un thread séparé.
    Utilisé pour les environnements comme Replit pour éviter que l'instance soit mise en veille.
    """
    try:
        app.run(host="0.0.0.0", port=KEEPALIVE_PORT)
    except Exception as e:
        # Si le serveur ne démarre pas, on ignore (par ex. sur un hébergement qui n'autorise pas Flask)
        print("Keepalive server error:", e)


def start_keepalive_thread() -> None:
    """
    Lance le thread du serveur keepalive.
    """
    t = Thread(target=run_keepalive_server, daemon=True)
    t.start()


# ---------------------------
# Load config helper
# ---------------------------
def load_config() -> Dict[str, Any]:
    cfg = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            print("Erreur lecture config.json:", e)
    return cfg


# ---------------------------
# Persistence: save / load data
# ---------------------------
def empty_data_template() -> Dict[str, Any]:
    return {
        "hosting_channels": {},  # guild_id -> {hosting_channel_id: {"type": "text"/"voice", "temp_category_id": id or None, "owner_id": int}}
        "temp_channels": {},     # guild_id -> {temp_channel_id: owner_id}
        "user_lang": {},         # user_id -> "en"/"fr"/"ar"
        "channel_lang": {},      # channel_id -> "en"/"fr"/"ar"
        "server_lang": {},       # guild_id -> "en"/"fr"/"ar"
        "keepalive_config": {}   # guild_id -> {"channel_id": int, "interval_minutes": int, "message": str, "last_sent": float}
    }


def load_data() -> Dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        data = empty_data_template()
        save_data(data)
        return data
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # ensure keys exist
            base = empty_data_template()
            for k in base:
                if k not in data:
                    data[k] = base[k]
            return data
    except Exception as e:
        print("Erreur lors du chargement des données :", e)
        # fallback to empty
        data = empty_data_template()
        save_data(data)
        return data


def save_data(data: Dict[str, Any]) -> None:
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Erreur lors de la sauvegarde des données :", e)


# ---------------------------
# Translations
# ---------------------------
translations = {
    "setup_hosting_success": {
        "en": "Hosting channel configured successfully.",
        "fr": "Canal d'hébergement configuré avec succès.",
        "ar": "تم إعداد قناة الاستضافة بنجاح."
    },
    "no_permission": {
        "en": "You don't have permission to do that.",
        "fr": "Vous n'avez pas la permission.",
        "ar": "ليس لديك الصلاحية للقيام بذلك."
    },
    "lang_set_user": {
        "en": "Your language preference has been set to {lang}.",
        "fr": "Votre langue a été définie sur : {lang}.",
        "ar": "تم تعيين لغتك المفضلة إلى {lang}."
    },
    "lang_set_channel": {
        "en": "Channel language set to: {lang}",
        "fr": "Langue du canal définie sur : {lang}",
        "ar": "تم تعيين لغة القناة إلى: {lang}"
    },
    "lang_set_server": {
        "en": "Server language set to: {lang}",
        "fr": "Langue du serveur définie sur : {lang}",
        "ar": "تم تعيين لغة الخادم إلى: {lang}"
    },
    "invalid_lang": {
        "en": "Invalid language. Choose: en, fr, ar.",
        "fr": "Langue invalide. Choisissez : en, fr, ar.",
        "ar": "لغة غير صالحة. اختر: en, fr, ar."
    },
    "hosting_not_found": {
        "en": "Hosting channel not found.",
        "fr": "Canal d'hébergement introuvable.",
        "ar": "قناة الاستضافة غير موجودة."
    },
    "temp_created": {
        "en": "Temporary channel created: {channel}",
        "fr": "Canal temporaire créé : {channel}",
        "ar": "تم إنشاء القناة المؤقتة: {channel}"
    },
    "hosting_removed": {
        "en": "Hosting channel removed successfully.",
        "fr": "Canal d'hébergement supprimé avec succès.",
        "ar": "تمت إزالة قناة الاستضافة بنجاح."
    },
    "list_hosting_empty": {
        "en": "No hosting channels configured.",
        "fr": "Aucun canal d'hébergement configuré.",
        "ar": "لا توجد قنوات استضافة مهيأة."
    },
    "list_hosting_title": {
        "en": "Hosting Channels:",
        "fr": "Canaux d'hébergement :",
        "ar": "قنوات الاستضافة:"
    },
    "invite_success_voice": {
        "en": "{user} has been moved to the voice channel {channel}.",
        "fr": "{user} a été déplacé dans le salon vocal {channel}.",
        "ar": "{user} تم نقله إلى قناة الصوت {channel}."
    },
    "invite_success_text": {
        "en": "{user} has been invited to the text channel {channel}.",
        "fr": "{user} a été invité dans le salon textuel {channel}.",
        "ar": "{user} تمت دعوته إلى قناة النص {channel}."
    },
    "invite_fail_not_connected": {
        "en": "{user} is not connected to any voice channel.",
        "fr": "{user} n'est connecté à aucun salon vocal.",
        "ar": "{user} غير متصل بأي قناة صوتية."
    },
    "change_host_success": {
        "en": "Ownership transferred to {new_host}.",
        "fr": "Propriété transférée à {new_host}.",
        "ar": "تم نقل الملكية إلى {new_host}."
    },
    "not_owner": {
        "en": "Only the current owner can transfer ownership.",
        "fr": "Seul le propriétaire actuel peut transférer la propriété.",
        "ar": "فقط المالك الحالي يمكنه نقل الملكية."
    },
    "keepalive_set": {
        "en": "Keepalive configured for {channel} every {interval} minutes.",
        "fr": "Keepalive configuré pour {channel} toutes les {interval} minutes.",
        "ar": "تم إعداد Keepalive لـ {channel} كل {interval} دقيقة."
    },
    "keepalive_removed": {
        "en": "Keepalive configuration removed.",
        "fr": "Configuration Keepalive supprimée.",
        "ar": "تمت إزالة إعداد Keepalive."
    },
    "keepalive_status": {
        "en": "Keepalive active in {channel}, every {interval} minutes, message: {message}",
        "fr": "Keepalive actif dans {channel}, toutes les {interval} minutes, message : {message}",
        "ar": "Keepalive نشط في {channel}، كل {interval} دقيقة، الرسالة: {message}"
    },
    "hosting_channel_not_temp": {
        "en": "This channel is not a temporary or hosting channel.",
        "fr": "Ce canal n'est pas un canal temporaire ou d'hébergement.",
        "ar": "هذه القناة ليست قناة مؤقتة أو قناة استضافة."
    },
    "user_not_connected_voice": {
        "en": "{user} is not connected to any voice channel.",
        "fr": "{user} n'est pas connecté à un salon vocal.",
        "ar": "{user} غير متصل بأي قناة صوتية."
    },
    "already_max_temp": {
        "en": "You already have 3 active temporary channels. Close one to create a new one.",
        "fr": "Tu as déjà 3 canaux temporaires actifs. Ferme-en un pour en créer un nouveau.",
        "ar": "لديك بالفعل 3 قنوات مؤقتة نشطة. أغلق واحدة لإنشاء جديدة."
    },
    "created_temp_voice": {
        "en": "Created a temporary voice channel: {channel}. ({count}/3)",
        "fr": "Canal vocal temporaire créé : {channel}. ({count}/3)",
        "ar": "تم إنشاء قناة صوتية مؤقتة: {channel}. ({count}/3)"
    },
    "created_temp_text": {
        "en": "Created a temporary text channel: {channel}. ({count}/3)",
        "fr": "Canal textuel temporaire créé : {channel}. ({count}/3)",
        "ar": "تم إنشاء قناة نصية مؤقتة: {channel}. ({count}/3)"
    },
    "deleted_temp": {
        "en": "Temporary channel {channel} deleted.",
        "fr": "Canal temporaire {channel} supprimé.",
        "ar": "تم حذف القناة المؤقتة {channel}."
    },
    "no_temp_to_delete": {
        "en": "You have no temporary channel to delete.",
        "fr": "Tu n'as aucun canal temporaire à supprimer.",
        "ar": "ليس لديك قناة مؤقتة للحذف."
    }
}

# ---------------------------
# Helpers for translations & language
# ---------------------------
def tr(data: Dict[str, Any], guild_id: Optional[int], user_id: Optional[int], channel_id: Optional[int], key: str, **kwargs) -> str:
    """
    Retourne la traduction pour la clé 'key' en vérifiant l'ordre:
    user_lang -> channel_lang -> server_lang -> 'fr' par défaut.
    """
    user_langs = data.get("user_lang", {})
    channel_langs = data.get("channel_lang", {})
    server_langs = data.get("server_lang", {})

    lang = None
    if user_id and str(user_id) in user_langs:
        lang = user_langs[str(user_id)]
    elif channel_id and str(channel_id) in channel_langs:
        lang = channel_langs[str(channel_id)]
    elif guild_id and str(guild_id) in server_langs:
        lang = server_langs[str(guild_id)]
    else:
        lang = "fr"

    text = translations.get(key, {}).get(lang)
    if not text:
        # fallback simple
        text = key
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text


def get_lang_pref(data: Dict[str, Any], guild_id: Optional[int], user_id: Optional[int], channel_id: Optional[int]) -> str:
    """
    Récupère le code langue effectif pour l'utilisateur/canal/serveur.
    """
    user_langs = data.get("user_lang", {})
    channel_langs = data.get("channel_lang", {})
    server_langs = data.get("server_lang", {})

    if user_id and str(user_id) in user_langs:
        return user_langs[str(user_id)]
    if channel_id and str(channel_id) in channel_langs:
        return channel_langs[str(channel_id)]
    if guild_id and str(guild_id) in server_langs:
        return server_langs[str(guild_id)]
    return "fr"


# ---------------------------
# Core bot setup
# ---------------------------
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.voice_states = True
intents.messages = True
intents.message_content = True  # si tu veux utiliser les commandes prefix

# Charger config (optionnel)
_config = load_config()
TOKEN = os.environ.get("DISCORD_TOKEN") or _config.get("token") or ""
CLIENT_ID = os.environ.get("CLIENT_ID") or _config.get("client_id") or None

# Create bot with both commands.Bot and app commands (slash)
bot = commands.Bot(command_prefix="!", intents=intents)


# ---------------------------
# Load persistent data at startup
# ---------------------------
DATA = load_data()
# We'll operate on DATA dict and call save_data(DATA) after each write change.

# Utility: helper to ensure keys exist in DATA maps (string keys for JSON uniformity)
def ensure_guild_maps(guild_id: int) -> None:
    """
    Ensure nested structures exist for the guild in DATA.
    """
    gid = str(guild_id)
    if "hosting_channels" not in DATA:
        DATA["hosting_channels"] = {}
    if gid not in DATA["hosting_channels"]:
        DATA["hosting_channels"][gid] = {}
    if "temp_channels" not in DATA:
        DATA["temp_channels"] = {}
    if gid not in DATA["temp_channels"]:
        DATA["temp_channels"][gid] = {}
    if "keepalive_config" not in DATA:
        DATA["keepalive_config"] = {}
    if "user_lang" not in DATA:
        DATA["user_lang"] = {}
    if "channel_lang" not in DATA:
        DATA["channel_lang"] = {}
    if "server_lang" not in DATA:
        DATA["server_lang"] = {}


# ---------------------------
# In-memory auxiliary caches
# ---------------------------
# We save to DATA for persistence, but keep an in-memory index for fast per-user count
# Structure: user_temp_count[guild_id][user_id] = [channel_ids...]
user_temp_index: Dict[str, Dict[str, List[str]]] = {}  # guild_id -> user_id -> [channel_id,...]


def rebuild_index_from_data() -> None:
    """
    Rebuild user_temp_index from DATA['temp_channels'] on startup.
    """
    global user_temp_index
    user_temp_index = {}
    tcs = DATA.get("temp_channels", {})
    for gid, mapping in tcs.items():
        user_temp_index[gid] = {}
        for ch_id, owner_id in mapping.items():
            owner_key = str(owner_id)
            if owner_key not in user_temp_index[gid]:
                user_temp_index[gid][owner_key] = []
            user_temp_index[gid][owner_key].append(str(ch_id))


rebuild_index_from_data()


# ---------------------------
# Keepalive loop (task) to send messages periodically
# ---------------------------
@tasks.loop(minutes=1.0)
async def keepalive_loop_task():
    """
    Tourne toutes les minutes et vérifie si des messages keepalive doivent être envoyés.
    La configuration se trouve dans DATA['keepalive_config'].
    """
    try:
        cfg_map = DATA.get("keepalive_config", {})
        now = time.time()
        for gid_str, cfg in list(cfg_map.items()):
            try:
                channel_id = cfg.get("channel_id")
                interval = int(cfg.get("interval_minutes", 1))
                message = cfg.get("message", "🔄 Keepalive")
                last_sent = float(cfg.get("last_sent", 0))
                if now - last_sent >= interval * 60:
                    # envoyer
                    channel = bot.get_channel(int(channel_id))
                    if channel:
                        await channel.send(message)
                        cfg["last_sent"] = now
                        save_data(DATA)
            except Exception:
                # ne pas interrompre la boucle pour une erreur d'un serveur
                print("Erreur keepalive pour guild", gid_str, traceback.format_exc())
    except Exception:
        print("Erreur dans keepalive_loop_task:", traceback.format_exc())


# ---------------------------
# Helper: check admin
# ---------------------------
def is_admin_member(member: discord.Member) -> bool:
    return member.guild_permissions.administrator


# ---------------------------
# App commands (slash) registration
# We'll create an app command tree on bot to offer slash commands.
# ---------------------------
# We'll register commands on on_ready to allow dynamic guild-scoped registration if CLIENT_ID and guild known.
# Also provide fallback prefix commands for older clients.


# ---------------------------
# Utility functions to manage temp channels with limit 3 per user
# ---------------------------
MAX_TEMP_PER_USER = 3


def get_user_temp_count(guild_id: int, user_id: int) -> int:
    gid = str(guild_id)
    uid = str(user_id)
    return len(user_temp_index.get(gid, {}).get(uid, []))


def add_temp_channel_record(guild_id: int, channel_id: int, owner_id: int) -> None:
    gid = str(guild_id)
    cid = str(channel_id)
    oid = int(owner_id)
    # DATA update
    DATA.setdefault("temp_channels", {})
    DATA["temp_channels"].setdefault(gid, {})
    DATA["temp_channels"][gid][cid] = oid
    save_data(DATA)
    # index update
    user_temp_index.setdefault(gid, {})
    user_temp_index[gid].setdefault(str(oid), [])
    if cid not in user_temp_index[gid][str(oid)]:
        user_temp_index[gid][str(oid)].append(cid)


def remove_temp_channel_record(guild_id: int, channel_id: int) -> None:
    gid = str(guild_id)
    cid = str(channel_id)
    tcs = DATA.get("temp_channels", {}).get(gid, {})
    owner_id = tcs.get(cid)
    if owner_id is not None:
        # remove from DATA
        try:
            del DATA["temp_channels"][gid][cid]
        except Exception:
            pass
        save_data(DATA)
        # remove from index
        uid = str(owner_id)
        if gid in user_temp_index and uid in user_temp_index[gid]:
            user_temp_index[gid][uid] = [x for x in user_temp_index[gid][uid] if x != cid]
            if not user_temp_index[gid][uid]:
                del user_temp_index[gid][uid]


def list_user_temp_channels(guild_id: int, user_id: int) -> List[int]:
    gid = str(guild_id)
    uid = str(user_id)
    return [int(x) for x in user_temp_index.get(gid, {}).get(uid, [])]


# ---------------------------
# Commands (slash + prefix fallback)
# ---------------------------

# We'll implement the main commands as app commands but provide prefix commands where the user already uses prefix style.

# Helper to send translation-aware responses
async def send_tr_msg(ctx_or_interaction, key: str, **kwargs):
    """
    ctx_or_interaction can be a commands.Context (prefix) or discord.Interaction (slash).
    This helper sends a message using the proper send method and translation.
    """
    try:
        if isinstance(ctx_or_interaction, discord.Interaction):
            guild_id = ctx_or_interaction.guild.id if ctx_or_interaction.guild else None
            user_id = ctx_or_interaction.user.id if ctx_or_interaction.user else None
            channel_id = ctx_or_interaction.channel.id if ctx_or_interaction.channel else None
            text = tr(DATA, guild_id, user_id, channel_id, key, **kwargs)
            # Prefer response if not yet responded
            if ctx_or_interaction.response.is_done():
                await ctx_or_interaction.followup.send(text)
            else:
                await ctx_or_interaction.response.send_message(text)
        else:
            # commands.Context
            ctx = ctx_or_interaction
            guild_id = ctx.guild.id if ctx.guild else None
            user_id = ctx.author.id if ctx.author else None
            channel_id = ctx.channel.id if ctx.channel else None
            text = tr(DATA, guild_id, user_id, channel_id, key, **kwargs)
            await ctx.send(text)
    except Exception:
        # Fallback raw send
        try:
            if isinstance(ctx_or_interaction, discord.Interaction):
                if not ctx_or_interaction.response.is_done():
                    await ctx_or_interaction.response.send_message(key)
                else:
                    await ctx_or_interaction.followup.send(key)
            else:
                await ctx_or_interaction.send(key)
        except Exception:
            print("Erreur en envoyant le message traduit.")


# ---------- Slash command: setup_hosting ----------
@bot.tree.command(name="setup_hosting", description="Configure a channel for hosting temporary channels")
@app_commands.describe(
    channel="The channel to use for hosting",
    channel_type="Type of channels to create (text or voice)",
    temp_category="Category for temporary channels (optional)"
)
@app_commands.default_permissions(administrator=True)
async def slash_setup_hosting(interaction: discord.Interaction, channel: discord.abc.GuildChannel, channel_type: str, temp_category: Optional[discord.CategoryChannel] = None):
    """
    Configurer un channel d'hébergement via slash command.
    channel_type: 'text' ou 'voice'
    """
    try:
        if channel_type.lower() not in ("text", "voice"):
            await interaction.response.send_message("channel_type must be 'text' or 'voice'")
            return

        guild_id = interaction.guild.id
        ensure_guild_maps(guild_id)
        gid = str(guild_id)
        DATA["hosting_channels"].setdefault(gid, {})
        DATA["hosting_channels"][gid][str(channel.id)] = {
            "type": channel_type.lower(),
            "temp_category_id": temp_category.id if temp_category else (DEFAULT_TEMP_CATEGORY_ID if DEFAULT_TEMP_CATEGORY_ID else None),
            "owner_id": interaction.user.id
        }
        save_data(DATA)
        await send_tr_msg(interaction, "setup_hosting_success")
    except Exception as e:
        print("setup_hosting error:", e, traceback.format_exc())
        await interaction.response.send_message(f"Erreur: {e}")


# ---------- Slash command: create_temp ----------
@bot.tree.command(name="create_temp", description="Create a temporary channel (text or voice)")
@app_commands.describe(name="Name for the temporary channel", channel_type="Type of channel (voice or text)")
async def slash_create_temp(interaction: discord.Interaction, name: str, channel_type: str = "voice"):
    """
    Create a temp channel by slash. This is user command to directly create a personal temporary channel.
    channel_type: 'text' or 'voice'
    Enforce max 3 per user across the guild.
    """
    await interaction.response.defer(ephemeral=True)
    try:
        channel_type = channel_type.lower()
        if channel_type not in ("text", "voice"):
            await interaction.followup.send("channel_type must be 'text' or 'voice'")
            return

        guild = interaction.guild
        guild_id = guild.id
        # Count existing
        cnt = get_user_temp_count(guild_id, interaction.user.id)
        if cnt >= MAX_TEMP_PER_USER:
            await interaction.followup.send(tr(DATA, guild_id, interaction.user.id, interaction.channel.id, "already_max_temp"))
            return

        # Determine category (try server hosting default if any, else DEFAULT_TEMP_CATEGORY_ID)
        cat = None
        # Try to get a hosting entry for the current channel
        hosting_map = DATA.get("hosting_channels", {}).get(str(guild_id), {})
        # choose any hosting channel that has a temp_category defined
        temp_cat_id = None
        for _, info in hosting_map.items():
            if info.get("temp_category_id"):
                temp_cat_id = info.get("temp_category_id")
                break
        if temp_cat_id:
            cat = guild.get_channel(int(temp_cat_id))
        elif DEFAULT_TEMP_CATEGORY_ID:
            cat = guild.get_channel(int(DEFAULT_TEMP_CATEGORY_ID))

        if channel_type == "voice":
            # create voice channel
            new_channel = await guild.create_voice_channel(name, category=cat)
            add_temp_channel_record(guild_id, new_channel.id, interaction.user.id)
            current_count = get_user_temp_count(guild_id, interaction.user.id)
            await interaction.followup.send(tr(DATA, guild_id, interaction.user.id, interaction.channel.id, "created_temp_voice", channel=new_channel.mention, count=current_count))
            # schedule auto-clean: we'll create a background wait task to delete channel when empty for a period
            bot.loop.create_task(_auto_delete_when_empty(new_channel, guild_id))
        else:
            new_channel = await guild.create_text_channel(name, category=cat)
            # restrict default role view then allow owner
            await new_channel.set_permissions(guild.default_role, view_channel=False)
            await new_channel.set_permissions(interaction.user, view_channel=True, send_messages=True)
            add_temp_channel_record(guild_id, new_channel.id, interaction.user.id)
            current_count = get_user_temp_count(guild_id, interaction.user.id)
            await interaction.followup.send(tr(DATA, guild_id, interaction.user.id, interaction.channel.id, "created_temp_text", channel=new_channel.mention, count=current_count))
            # no auto-delete schedule for text by join/leave; we can schedule TTL or deletion when owner uses delete_temp
    except Exception as e:
        print("create_temp slash error:", e, traceback.format_exc())
        try:
            await interaction.followup.send(f"Erreur lors de la création: {e}")
        except Exception:
            pass


# ---------- Slash command: delete_temp ----------
@bot.tree.command(name="delete_temp", description="Delete one of your temporary channels")
@app_commands.describe(channel="The temporary channel to delete (mention or id)")
async def slash_delete_temp(interaction: discord.Interaction, channel: discord.abc.GuildChannel):
    await interaction.response.defer(ephemeral=True)
    try:
        guild_id = interaction.guild.id
        cid = str(channel.id)
        tmap = DATA.get("temp_channels", {}).get(str(guild_id), {})
        if cid not in tmap:
            await interaction.followup.send(tr(DATA, guild_id, interaction.user.id, interaction.channel.id, "no_temp_to_delete"))
            return
        owner = tmap[cid]
        if owner != interaction.user.id and not is_admin_member(interaction.user):
            await interaction.followup.send(tr(DATA, guild_id, interaction.user.id, interaction.channel.id, "no_permission"))
            return
        # delete channel
        try:
            await channel.delete()
        except Exception:
            pass
        remove_temp_channel_record(guild_id, channel.id)
        await interaction.followup.send(tr(DATA, guild_id, interaction.user.id, interaction.channel.id, "deleted_temp", channel=channel.name))
    except Exception as e:
        print("delete_temp slash error:", e, traceback.format_exc())
        try:
            await interaction.followup.send(f"Erreur: {e}")
        except Exception:
            pass


# ---------- Slash command: list_temp ----------
@bot.tree.command(name="list_temp", description="List your active temporary channels")
async def slash_list_temp(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        guild_id = interaction.guild.id
        user_id = interaction.user.id
        chs = list_user_temp_channels(guild_id, user_id)
        if not chs:
            await interaction.followup.send(tr(DATA, guild_id, user_id, interaction.channel.id, "list_hosting_empty"))
            return
        parts = []
        for cid in chs:
            ch = bot.get_channel(cid)
            if ch:
                parts.append(f"- {ch.mention} ({ch.name})")
            else:
                parts.append(f"- {cid} (non trouvé)")
        await interaction.followup.send("📋 Vos canaux temporaires :\n" + "\n".join(parts))
    except Exception as e:
        print("list_temp slash error:", e, traceback.format_exc())
        try:
            await interaction.followup.send(f"Erreur: {e}")
        except Exception:
            pass


# ---------- Slash commands: locale management ----------
@bot.tree.command(name="set_lang_user", description="Set your language preference")
@app_commands.choices(lang_code=[
    app_commands.Choice(name="fr", value="fr"),
    app_commands.Choice(name="en", value="en"),
    app_commands.Choice(name="ar", value="ar")
])
async def slash_set_lang_user(interaction: discord.Interaction, lang_code: app_commands.Choice[str]):
    await interaction.response.defer(ephemeral=True)
    try:
        code = lang_code.value
        DATA.setdefault("user_lang", {})[str(interaction.user.id)] = code
        save_data(DATA)
        names = {"en": "English", "fr": "Français", "ar": "العربية"}
        await interaction.followup.send(tr(DATA, interaction.guild.id, interaction.user.id, interaction.channel.id, "lang_set_user", lang=names.get(code, code)))
    except Exception as e:
        print("set_lang_user error:", e, traceback.format_exc())
        try:
            await interaction.followup.send("Erreur lors du changement de langue.")
        except Exception:
            pass


@bot.tree.command(name="set_lang_channel", description="Set channel language preference (Admin only)")
@app_commands.default_permissions(administrator=True)
@app_commands.choices(lang_code=[
    app_commands.Choice(name="fr", value="fr"),
    app_commands.Choice(name="en", value="en"),
    app_commands.Choice(name="ar", value="ar")
])
async def slash_set_lang_channel(interaction: discord.Interaction, lang_code: app_commands.Choice[str]):
    await interaction.response.defer(ephemeral=True)
    try:
        code = lang_code.value
        DATA.setdefault("channel_lang", {})[str(interaction.channel.id)] = code
        save_data(DATA)
        names = {"en": "English", "fr": "Français", "ar": "العربية"}
        await interaction.followup.send(tr(DATA, interaction.guild.id, interaction.user.id, interaction.channel.id, "lang_set_channel", lang=names.get(code, code)))
    except Exception as e:
        print("set_lang_channel error:", e, traceback.format_exc())
        try:
            await interaction.followup.send("Erreur lors du changement de langue du canal.")
        except Exception:
            pass


@bot.tree.command(name="set_lang_server", description="Set server language preference (Admin only)")
@app_commands.default_permissions(administrator=True)
@app_commands.choices(lang_code=[
    app_commands.Choice(name="fr", value="fr"),
    app_commands.Choice(name="en", value="en"),
    app_commands.Choice(name="ar", value="ar")
])
async def slash_set_lang_server(interaction: discord.Interaction, lang_code: app_commands.Choice[str]):
    await interaction.response.defer(ephemeral=True)
    try:
        code = lang_code.value
        DATA.setdefault("server_lang", {})[str(interaction.guild.id)] = code
        save_data(DATA)
        names = {"en": "English", "fr": "Français", "ar": "العربية"}
        await interaction.followup.send(tr(DATA, interaction.guild.id, interaction.user.id, interaction.channel.id, "lang_set_server", lang=names.get(code, code)))
    except Exception as e:
        print("set_lang_server error:", e, traceback.format_exc())
        try:
            await interaction.followup.send("Erreur lors du changement de langue du serveur.")
        except Exception:
            pass


@bot.tree.command(name="clear_lang_user", description="Clear your language preference")
async def slash_clear_lang_user(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        DATA.get("user_lang", {}).pop(str(interaction.user.id), None)
        save_data(DATA)
        await interaction.followup.send("✅ Langue utilisateur réinitialisée.")
    except Exception as e:
        print("clear_lang_user error:", e, traceback.format_exc())
        try:
            await interaction.followup.send("Erreur lors de la réinitialisation.")
        except Exception:
            pass


@bot.tree.command(name="clear_lang_channel", description="Clear channel language preference (Admin only)")
@app_commands.default_permissions(administrator=True)
async def slash_clear_lang_channel(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        DATA.get("channel_lang", {}).pop(str(interaction.channel.id), None)
        save_data(DATA)
        await interaction.followup.send("✅ Langue du canal réinitialisée.")
    except Exception as e:
        print("clear_lang_channel error:", e, traceback.format_exc())
        try:
            await interaction.followup.send("Erreur lors de la réinitialisation.")
        except Exception:
            pass


@bot.tree.command(name="clear_lang_server", description="Clear server language preference (Admin only)")
@app_commands.default_permissions(administrator=True)
async def slash_clear_lang_server(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        DATA.get("server_lang", {}).pop(str(interaction.guild.id), None)
        save_data(DATA)
        await interaction.followup.send("✅ Langue du serveur réinitialisée.")
    except Exception as e:
        print("clear_lang_server error:", e, traceback.format_exc())
        try:
            await interaction.followup.send("Erreur lors de la réinitialisation.")
        except Exception:
            pass


# ---------- Slash admin commands: remove_hosting, list_hosting ----------
@bot.tree.command(name="remove_hosting", description="Remove a hosting channel configuration (Admin only)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(channel="The channel to remove from hosting")
async def slash_remove_hosting(interaction: discord.Interaction, channel: discord.abc.GuildChannel):
    await interaction.response.defer(ephemeral=True)
    try:
        guild_id = interaction.guild.id
        gid = str(guild_id)
        if gid in DATA.get("hosting_channels", {}) and str(channel.id) in DATA["hosting_channels"].get(gid, {}):
            del DATA["hosting_channels"][gid][str(channel.id)]
            save_data(DATA)
            await interaction.followup.send(tr(DATA, guild_id, interaction.user.id, interaction.channel.id, "hosting_removed"))
        else:
            await interaction.followup.send(tr(DATA, guild_id, interaction.user.id, interaction.channel.id, "hosting_not_found"))
    except Exception as e:
        print("remove_hosting error:", e, traceback.format_exc())
        try:
            await interaction.followup.send("Erreur lors de la suppression de l'hébergement.")
        except Exception:
            pass


@bot.tree.command(name="list_hosting", description="List all configured hosting channels for this server")
async def slash_list_hosting(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        guild_id = interaction.guild.id
        gid = str(guild_id)
        guild_map = DATA.get("hosting_channels", {}).get(gid, {})
        if not guild_map:
            await interaction.followup.send(tr(DATA, guild_id, interaction.user.id, interaction.channel.id, "list_hosting_empty"))
            return
        lines = [tr(DATA, guild_id, interaction.user.id, interaction.channel.id, "list_hosting_title")]
        for ch_id, info in guild_map.items():
            ch = interaction.guild.get_channel(int(ch_id))
            owner = interaction.guild.get_member(info.get("owner_id")) if info.get("owner_id") else None
            lines.append(f"- {ch.mention if ch else 'Unknown'} (type: {info.get('type')}, owner: {owner.display_name if owner else 'Unknown'})")
        await interaction.followup.send("\n".join(lines))
    except Exception as e:
        print("list_hosting error:", e, traceback.format_exc())
        try:
            await interaction.followup.send("Erreur lors de la liste des hébergements.")
        except Exception:
            pass


# ---------- Command: invite (prefix) ----------
@bot.command(name="invite")
@commands.has_guild_permissions(manage_channels=True)
async def cmd_invite(ctx: commands.Context, member: discord.Member, channel: Optional[discord.abc.GuildChannel] = None):
    """
    Invite a member to a temp channel (voice or text).
    Usage:
      !invite @user      -> invites to current channel (if temp/hosting)
      !invite @user #ch  -> invites to specified channel (if temp/hosting)
    """
    try:
        channel = channel or ctx.channel
        guild = ctx.guild
        guild_id = guild.id
        guild_hostings = DATA.get("hosting_channels", {}).get(str(guild_id), {})
        is_temp = False
        owner_id = None

        if str(channel.id) in DATA.get("temp_channels", {}).get(str(guild_id), {}):
            is_temp = True
            owner_id = DATA["temp_channels"][str(guild_id)].get(str(channel.id))
        elif str(channel.id) in guild_hostings:
            is_temp = True
            owner_id = guild_hostings[str(channel.id)].get("owner_id")

        if not is_temp:
            await ctx.send(tr(DATA, guild_id, ctx.author.id, ctx.channel.id, "hosting_channel_not_temp"))
            return

        if isinstance(channel, discord.VoiceChannel):
            if not member.voice or not member.voice.channel:
                await ctx.send(tr(DATA, guild_id, ctx.author.id, ctx.channel.id, "user_not_connected_voice", user=member.display_name))
                return
            await member.move_to(channel)
            await ctx.send(tr(DATA, guild_id, ctx.author.id, ctx.channel.id, "invite_success_voice", user=member.display_name, channel=channel.name))
        else:
            await channel.set_permissions(member, view_channel=True, send_messages=True)
            await ctx.send(tr(DATA, guild_id, ctx.author.id, ctx.channel.id, "invite_success_text", user=member.display_name, channel=channel.name))
    except commands.MissingPermissions:
        await ctx.send(tr(DATA, ctx.guild.id, ctx.author.id, ctx.channel.id, "no_permission"))
    except Exception as e:
        print("invite command error:", e, traceback.format_exc())
        await ctx.send(f"Erreur lors de l'invitation: {e}")


# ---------- Command: change_host (prefix) ----------
@bot.command(name="change_host")
async def cmd_change_host(ctx: commands.Context, new_host: discord.Member):
    """
    Transfer ownership of a temp or hosting channel to another user.
    Only current owner can transfer.
    """
    try:
        guild_id = ctx.guild.id
        channel_id = ctx.channel.id
        gid = str(guild_id)
        is_temp = False
        current_owner_id = None

        if gid in DATA.get("temp_channels", {}) and str(channel_id) in DATA["temp_channels"][gid]:
            is_temp = True
            current_owner_id = DATA["temp_channels"][gid][str(channel_id)]
        elif gid in DATA.get("hosting_channels", {}) and str(channel_id) in DATA["hosting_channels"][gid]:
            is_temp = True
            current_owner_id = DATA["hosting_channels"][gid][str(channel_id)].get("owner_id")

        if not is_temp:
            await ctx.send(tr(DATA, guild_id, ctx.author.id, ctx.channel.id, "hosting_channel_not_temp"))
            return

        if ctx.author.id != int(current_owner_id):
            await ctx.send(tr(DATA, guild_id, ctx.author.id, ctx.channel.id, "not_owner"))
            return

        # transfer
        if gid in DATA.get("temp_channels", {}) and str(channel_id) in DATA["temp_channels"][gid]:
            DATA["temp_channels"][gid][str(channel_id)] = new_host.id
            # update index
            if gid in user_temp_index:
                # remove from old
                old_owner = str(current_owner_id)
                if old_owner in user_temp_index[gid]:
                    user_temp_index[gid][old_owner] = [x for x in user_temp_index[gid][old_owner] if x != str(channel_id)]
                # add to new
                user_temp_index[gid].setdefault(str(new_host.id), [])
                user_temp_index[gid][str(new_host.id)].append(str(channel_id))
        elif gid in DATA.get("hosting_channels", {}) and str(channel_id) in DATA["hosting_channels"][gid]:
            DATA["hosting_channels"][gid][str(channel_id)]["owner_id"] = new_host.id

        save_data(DATA)
        await ctx.send(tr(DATA, guild_id, ctx.author.id, ctx.channel.id, "change_host_success", new_host=new_host.display_name))
    except Exception as e:
        print("change_host error:", e, traceback.format_exc())
        await ctx.send(f"Erreur: {e}")


# ---------- Keepalive configuration (slash) ----------
@bot.tree.command(name="setup_keepalive", description="Set up automatic keepalive messages")
@app_commands.describe(
    channel="The text channel for keepalive messages",
    interval_minutes="Interval in minutes between messages",
    message="The keepalive message to send"
)
@app_commands.default_permissions(administrator=True)
async def slash_setup_keepalive(interaction: discord.Interaction, channel: discord.TextChannel, interval_minutes: int, message: str = "🔄 Keepalive"):
    await interaction.response.defer(ephemeral=True)
    try:
        if interval_minutes < 1:
            await interaction.followup.send("The interval must be at least 1 minute.")
            return
        gid = str(interaction.guild.id)
        DATA.setdefault("keepalive_config", {})[gid] = {
            "channel_id": channel.id,
            "interval_minutes": interval_minutes,
            "message": message,
            "last_sent": 0
        }
        save_data(DATA)
        await interaction.followup.send(tr(DATA, interaction.guild.id, interaction.user.id, interaction.channel.id, "keepalive_set", channel=channel.mention, interval=interval_minutes))
    except Exception as e:
        print("setup_keepalive error:", e, traceback.format_exc())
        try:
            await interaction.followup.send("Erreur lors de la configuration keepalive.")
        except Exception:
            pass


@bot.command(name="remove_keepalive")
@commands.has_permissions(administrator=True)
async def cmd_remove_keepalive(ctx: commands.Context):
    gid = str(ctx.guild.id)
    if gid in DATA.get("keepalive_config", {}):
        del DATA["keepalive_config"][gid]
        save_data(DATA)
        await ctx.send(tr(DATA, ctx.guild.id, ctx.author.id, ctx.channel.id, "keepalive_removed"))
    else:
        await ctx.send("Aucune configuration keepalive trouvée.")


@bot.command(name="keepalive_status")
async def cmd_keepalive_status(ctx: commands.Context):
    gid = str(ctx.guild.id)
    if gid not in DATA.get("keepalive_config", {}):
        await ctx.send("Aucune configuration keepalive active.")
        return
    cfg = DATA["keepalive_config"][gid]
    channel = bot.get_channel(cfg["channel_id"])
    await ctx.send(tr(DATA, ctx.guild.id, ctx.author.id, ctx.channel.id, "keepalive_status", channel=channel.mention if channel else "Channel non trouvé", interval=cfg["interval_minutes"], message=cfg["message"]))


# ---------- Voice state / temp channel auto-create when joining hosting ----------
@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    """
    - Si l'utilisateur rejoint un channel configuré en hosting (type voice), on crée un channel temporaire et le déplace dedans.
    - Si l'utilisateur quitte un channel temporaire et le laisse vide, on supprime le channel.
    - Si changement de channel, on vérifie l'ancien pour suppression.
    """
    try:
        guild = member.guild
        if not guild:
            return
        gid = str(guild.id)

        # ----- JOINING a hosting channel -----
        if after.channel and gid in DATA.get("hosting_channels", {}) and str(after.channel.id) in DATA["hosting_channels"][gid]:
            hosting_info = DATA["hosting_channels"][gid][str(after.channel.id)]
            if hosting_info and hosting_info.get("type") == "voice":
                # Check user limit
                user_id = member.id
                if get_user_temp_count(guild.id, user_id) >= MAX_TEMP_PER_USER:
                    # send DM if possible
                    try:
                        await member.send(tr(DATA, guild.id, user_id, after.channel.id, "already_max_temp"))
                    except Exception:
                        pass
                    # optionally move back or do nothing
                    return

                # Create a new voice channel
                category = None
                if hosting_info.get("temp_category_id"):
                    try:
                        category = guild.get_channel(int(hosting_info["temp_category_id"]))
                    except Exception:
                        category = None
                elif DEFAULT_TEMP_CATEGORY_ID:
                    category = guild.get_channel(int(DEFAULT_TEMP_CATEGORY_ID))
                channel_name = f"{member.display_name}'s Channel"
                try:
                    new_channel = await guild.create_voice_channel(channel_name, category=category)
                    add_temp_channel_record(guild.id, new_channel.id, member.id)
                    # move the member
                    try:
                        await member.move_to(new_channel)
                    except Exception:
                        pass
                    print(f"Temporary voice channel created: {new_channel.name} for {member.display_name}")
                    # schedule auto-delete when empty
                    bot.loop.create_task(_auto_delete_when_empty(new_channel, guild.id))
                except Exception as e:
                    print("Erreur lors de la création du canal temporaire (voice):", e, traceback.format_exc())

        # ----- LEAVING a temp channel -----
        # If the user leaves a channel that was a temp and it's now empty => delete
        if before.channel and gid in DATA.get("temp_channels", {}) and str(before.channel.id) in DATA["temp_channels"][gid]:
            # If after.channel is None OR user switched to another channel, check emptiness
            ch = before.channel
            # If channel has no members:
            if ch and len(ch.members) == 0:
                try:
                    await ch.delete()
                except Exception:
                    pass
                remove_temp_channel_record(guild.id, ch.id)
                print(f"Deleted empty temporary channel: {ch.name}")

        # ----- SWITCHED channels: check old channel for cleanup -----
        if before.channel and after.channel and before.channel != after.channel:
            if gid in DATA.get("temp_channels", {}) and str(before.channel.id) in DATA["temp_channels"][gid]:
                if len(before.channel.members) == 0:
                    try:
                        await before.channel.delete()
                    except Exception:
                        pass
                    remove_temp_channel_record(guild.id, before.channel.id)
                    print(f"Deleted temporary channel on switch: {before.channel.name}")

    except Exception as e:
        print("on_voice_state_update error:", e, traceback.format_exc())


# ---------- on_message for text hosting auto-create ----------
@bot.event
async def on_message(message: discord.Message):
    """
    If a hosting channel is configured as text, when a user sends a message in that channel and they don't have a temp text channel,
    create it and DM them or post link.
    """
    try:
        # avoid bot messages
        if message.author.bot:
            return

        guild = message.guild
        if not guild:
            return

        gid = str(guild.id)
        # If guild has no hosting, ignore
        hosting_map = DATA.get("hosting_channels", {}).get(gid, {})
        if not hosting_map:
            # but still process commands
            await bot.process_commands(message)
            return

        # Check if the channel is configured as a text hosting
        hosting_info = hosting_map.get(str(message.channel.id))
        if hosting_info and hosting_info.get("type") == "text":
            # If user already has a temp channel, skip
            user_id = message.author.id
            if get_user_temp_count(guild.id, user_id) >= MAX_TEMP_PER_USER:
                # notify user via DM if possible
                try:
                    await message.author.send(tr(DATA, guild.id, user_id, message.channel.id, "already_max_temp"))
                except Exception:
                    pass
            else:
                # create new text channel
                category = None
                if hosting_info.get("temp_category_id"):
                    try:
                        category = guild.get_channel(int(hosting_info.get("temp_category_id")))
                    except Exception:
                        category = None
                elif DEFAULT_TEMP_CATEGORY_ID:
                    category = guild.get_channel(int(DEFAULT_TEMP_CATEGORY_ID))
                channel_name = f"{message.author.display_name}-temp"
                try:
                    temp_channel = await guild.create_text_channel(channel_name, category=category)
                    # restrict default role and allow the user + admins
                    await temp_channel.set_permissions(guild.default_role, view_channel=False)
                    await temp_channel.set_permissions(message.author, view_channel=True, send_messages=True)
                    # optionally allow admins: leave as general (admins usually have manage_channels)
                    add_temp_channel_record(guild.id, temp_channel.id, message.author.id)
                    await message.channel.send(tr(DATA, guild.id, message.author.id, message.channel.id, "temp_created", channel=temp_channel.mention))
                    await temp_channel.send(f"Welcome {message.author.mention}! This is your temporary channel.")
                    print(f"Temporary text channel created: {temp_channel.name} for {message.author.display_name}")
                except Exception as e:
                    print("Error creating temporary text channel:", e, traceback.format_exc())

        # allow commands to be processed (prefix)
        await bot.process_commands(message)
    except Exception as e:
        print("on_message handler error:", e, traceback.format_exc())


# ---------- Helper: auto-delete when empty (for voice channels) ----------
async def _auto_delete_when_empty(channel: discord.abc.GuildChannel, guild_id: int, timeout_seconds: int = 300):
    """
    Observe the channel and delete it when it becomes empty.
    timeout_seconds: check every 10 seconds and delete when empty; for reliability, if empty persists, delete after timeout_seconds.
    """
    try:
        # We'll wait in loop and delete when members==0
        total_wait = 0
        check_interval = 10
        while True:
            ch = bot.get_channel(channel.id)
            if ch is None:
                # already deleted
                remove_temp_channel_record(guild_id, channel.id)
                return
            # For voice channels check ch.members
            if isinstance(ch, discord.VoiceChannel):
                mem_count = len(ch.members)
            else:
                # for text channels we don't auto-delete here
                return
            if mem_count == 0:
                # wait a bit for transient leaves
                await asyncio.sleep(check_interval)
                total_wait += check_interval
                ch2 = bot.get_channel(channel.id)
                if ch2 is None:
                    remove_temp_channel_record(guild_id, channel.id)
                    return
                if len(ch2.members) == 0:
                    # delete
                    try:
                        await ch2.delete()
                    except Exception:
                        pass
                    remove_temp_channel_record(guild_id, channel.id)
                    print(f"Auto-deleted temporary channel {channel.name} after being empty.")
                    return
                else:
                    # someone joined again, continue loop
                    continue
            await asyncio.sleep(check_interval)
            total_wait += check_interval
            # safety: if function runs too long, break (but typically it will run until deletion)
            if total_wait > 60 * 60 * 6:  # 6 hours safety break
                return
    except Exception:
        print("Error in _auto_delete_when_empty:", traceback.format_exc())


# ---------- Event: on_ready ----------
@bot.event
async def on_ready():
    """
    Called when bot is ready. We start background tasks and sync app commands for the configured guild if provided.
    """
    try:
        print(f"Bot connecté en tant que {bot.user} (id: {bot.user.id})")
        # Start keepalive loop
        if not keepalive_loop_task.is_running():
            keepalive_loop_task.start()

        # Start Flask keepalive server thread (if running on Replit or similar)
        start_keepalive_thread()

        # Try syncing global commands if CLIENT_ID not set and there is a known guild config
        try:
            # If CLIENT_ID and guild id exist, you can sync to a specific guild for faster deployment
            if CLIENT_ID:
                # optionally sync to all guilds where bot is present (dangerous for large bots), we'll do a global sync
                synced = await bot.tree.sync()
                print(f"Synced {len(synced)} commands globally.")
            else:
                # global sync
                synced = await bot.tree.sync()
                print(f"Synced {len(synced)} commands.")
        except Exception as e:
            print("Erreur lors du sync des commandes:", e)
    except Exception:
        print("on_ready error:", traceback.format_exc())


# ---------- Prefix versions for some user convenience ----------
@bot.command(name="create_temp_prefix")
async def create_temp_prefix(ctx: commands.Context, *, name: str = "Temporary"):
    """
    Prefix command fallback for creating a temp voice channel.
    Equivalent to /create_temp name channel_type=voice
    """
    # We will call the slash handler logic programmatically (replicate minimal logic)
    try:
        user_id = ctx.author.id
        guild_id = ctx.guild.id
        if get_user_temp_count(guild_id, user_id) >= MAX_TEMP_PER_USER:
            await ctx.send(tr(DATA, guild_id, user_id, ctx.channel.id, "already_max_temp"))
            return
        # create
        cat = None
        # choose category from any hosting config that has temp_category_id
        hosting_map = DATA.get("hosting_channels", {}).get(str(guild_id), {})
        temp_cat_id = None
        for _, info in hosting_map.items():
            if info.get("temp_category_id"):
                temp_cat_id = info.get("temp_category_id")
                break
        if temp_cat_id:
            cat = ctx.guild.get_channel(int(temp_cat_id))
        elif DEFAULT_TEMP_CATEGORY_ID:
            cat = ctx.guild.get_channel(int(DEFAULT_TEMP_CATEGORY_ID))
        new_channel = await ctx.guild.create_voice_channel(name, category=cat)
        add_temp_channel_record(guild_id, new_channel.id, user_id)
        await ctx.send(tr(DATA, guild_id, user_id, ctx.channel.id, "created_temp_voice", channel=new_channel.mention, count=get_user_temp_count(guild_id, user_id)))
        bot.loop.create_task(_auto_delete_when_empty(new_channel, guild_id))
    except Exception as e:
        print("create_temp_prefix error:", e, traceback.format_exc())
        await ctx.send(f"Erreur: {e}")


@bot.command(name="delete_temp_prefix")
async def delete_temp_prefix(ctx: commands.Context, channel: Optional[discord.PartialMessage] = None):
    """
    Prefix fallback to delete a temp channel. If no channel id provided, delete all user's temps.
    """
    try:
        gid = ctx.guild.id
        uid = ctx.author.id
        if channel:
            # try parse id from mention or provided
            ch = channel
            ch_id = None
            # this prefix function signature used PartialMessage; better to accept int id, but keep simple
            await ctx.send("Utilise la commande: !delete_temp_prefix <channel_id>")
            return
        else:
            # delete all user's temp channels
            chs = list_user_temp_channels(gid, uid)
            if not chs:
                await ctx.send(tr(DATA, gid, uid, ctx.channel.id, "no_temp_to_delete"))
                return
            for cid in chs:
                ch = bot.get_channel(cid)
                if ch:
                    try:
                        await ch.delete()
                    except Exception:
                        pass
                remove_temp_channel_record(gid, cid)
            await ctx.send("🗑️ Tous tes salons temporaires ont été supprimés.")
    except Exception as e:
        print("delete_temp_prefix error:", e, traceback.format_exc())
        await ctx.send(f"Erreur: {e}")


@bot.command(name="list_temp_prefix")
async def list_temp_prefix(ctx: commands.Context):
    try:
        gid = ctx.guild.id
        uid = ctx.author.id
        chs = list_user_temp_channels(gid, uid)
        if not chs:
            await ctx.send("📭 Tu n'as pas de canal temporaire actif.")
            return
        lines = []
        for cid in chs:
            ch = bot.get_channel(cid)
            if ch:
                lines.append(f"- {ch.mention} ({ch.name})")
            else:
                lines.append(f"- {cid} (non trouvé)")
        await ctx.send("📋 Tes canaux temporaires :\n" + "\n".join(lines))
    except Exception as e:
        print("list_temp_prefix error:", e, traceback.format_exc())
        await ctx.send(f"Erreur: {e}")


# ---------- Utility: graceful shutdown saving data ----------
async def _graceful_shutdown():
    try:
        print("Saving data before shutdown...")
        save_data(DATA)
    except Exception:
        pass


# ---------- Signal handlers (optional) ----------
# Not adding OS signal handling to keep code simpler; ensure to call save_data on any manual shutdown.

# ---------- Main entry ----------
if __name__ == "__main__":
    # Ensure we save data before quitting with ctrl+c via a basic try/finally pattern when running
    try:
        # Optionally use config file token if no env token
        if not TOKEN:
            # try config.json token
            cfg = _config
            TOKEN = cfg.get("token") or TOKEN
        if not TOKEN:
            print("ERREUR: Token Discord non fourni. Place ton token dans la variable d'environnement DISCORD_TOKEN ou config.json.")
            exit(1)
        # Start the bot
        bot.run(TOKEN)
    finally:
        # Save DATA at shutdown
        try:
            save_data(DATA)
        except Exception:
            pass

# End of bot.py
