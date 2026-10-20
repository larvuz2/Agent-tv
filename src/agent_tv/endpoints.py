"""SSAP and Luna endpoint URIs used by webOS TVs.

``ssap://`` endpoints are the public second-screen API. ``luna://`` endpoints are
internal services; the TV only lets us reach them through the "alert trick"
(see ``SSAPClient.luna``), and it never returns their result.
"""

# --- system / info
GET_SYSTEM_INFO = "ssap://system/getSystemInfo"
GET_SOFTWARE_INFO = "ssap://com.webos.service.update/getCurrentSWInformation"
GET_SERVICE_LIST = "ssap://api/getServiceList"
GET_CONNECTION_INFO = "ssap://com.webos.service.connectionmanager/getinfo"
GET_CONFIGS = "ssap://config/getConfigs"

# --- power
POWER_OFF = "ssap://system/turnOff"
GET_POWER_STATE = "ssap://com.webos.service.tvpower/power/getPowerState"
TURN_OFF_SCREEN = "ssap://com.webos.service.tvpower/power/turnOffScreen"
TURN_ON_SCREEN = "ssap://com.webos.service.tvpower/power/turnOnScreen"
# webOS 4.x and older used a different service name for the screen
TURN_OFF_SCREEN_LEGACY = "ssap://com.webos.service.tv.power/turnOffScreen"
TURN_ON_SCREEN_LEGACY = "ssap://com.webos.service.tv.power/turnOnScreen"
REQUEST_REBOOT = "ssap://com.webos.service.devicereset/requestReboot"

# --- audio
GET_AUDIO_STATUS = "ssap://audio/getStatus"
GET_VOLUME = "ssap://audio/getVolume"
SET_VOLUME = "ssap://audio/setVolume"
VOLUME_UP = "ssap://audio/volumeUp"
VOLUME_DOWN = "ssap://audio/volumeDown"
SET_MUTE = "ssap://audio/setMute"
GET_SOUND_OUTPUT = "ssap://com.webos.service.apiadapter/audio/getSoundOutput"
CHANGE_SOUND_OUTPUT = "ssap://com.webos.service.apiadapter/audio/changeSoundOutput"

# --- apps
LIST_LAUNCH_POINTS = "ssap://com.webos.applicationManager/listLaunchPoints"
LIST_APPS = "ssap://com.webos.applicationManager/listApps"
GET_FOREGROUND_APP = "ssap://com.webos.applicationManager/getForegroundAppInfo"
GET_MEDIA_FOREGROUND_APP = "ssap://com.webos.media/getForegroundAppInfo"
LAUNCH = "ssap://system.launcher/launch"
OPEN_URL = "ssap://system.launcher/open"
CLOSE_APP = "ssap://system.launcher/close"
GET_APP_STATE = "ssap://system.launcher/getAppState"

# --- inputs / channels
GET_INPUTS = "ssap://tv/getExternalInputList"
SWITCH_INPUT = "ssap://tv/switchInput"
GET_CHANNELS = "ssap://tv/getChannelList"
GET_CURRENT_CHANNEL = "ssap://tv/getCurrentChannel"
GET_CHANNEL_PROGRAM_INFO = "ssap://tv/getChannelProgramInfo"
OPEN_CHANNEL = "ssap://tv/openChannel"
CHANNEL_UP = "ssap://tv/channelUp"
CHANNEL_DOWN = "ssap://tv/channelDown"
SCREENSHOT = "ssap://tv/executeOneShot"

# --- media transport
MEDIA_PLAY = "ssap://media.controls/play"
MEDIA_PAUSE = "ssap://media.controls/pause"
MEDIA_STOP = "ssap://media.controls/stop"
MEDIA_REWIND = "ssap://media.controls/rewind"
MEDIA_FAST_FORWARD = "ssap://media.controls/fastForward"

# --- keyboard / pointer
INSERT_TEXT = "ssap://com.webos.service.ime/insertText"
SEND_ENTER = "ssap://com.webos.service.ime/sendEnterKey"
DELETE_CHARACTERS = "ssap://com.webos.service.ime/deleteCharacters"
POINTER_SOCKET = "ssap://com.webos.service.networkinput/getPointerInputSocket"

# --- notifications
CREATE_TOAST = "ssap://system.notifications/createToast"
CREATE_ALERT = "ssap://system.notifications/createAlert"
CLOSE_ALERT = "ssap://system.notifications/closeAlert"

# --- settings
GET_SYSTEM_SETTINGS = "ssap://settings/getSystemSettings"
SET_SYSTEM_SETTINGS = "ssap://settings/setSystemSettings"

# --- internal luna services (reachable only via the alert trick, write-only)
LUNA_SET_SYSTEM_SETTINGS = "com.webos.settingsservice/setSystemSettings"
LUNA_SHOW_INPUT_PICKER = "com.webos.surfacemanager/showInputPicker"
LUNA_TURN_ON_SCREEN_SAVER = "com.webos.service.tvpower/power/turnOnScreenSaver"
