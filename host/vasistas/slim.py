"""Allègement de Windows : télémétrie, applications inutiles, services, tâches, composants.

Le catalogue est ici (textes pour l'application compagnon, niveaux) ; le travail se fait dans
l'invité par guest/slim.ps1, envoyé par `exec`. Chaque réglage garde sa valeur d'origine dans
C:\\ProgramData\\Vasistas\\slim-backup.json, sauf les suppressions d'applications et de composants
(définitives : l'instantané du disque pris avant sert de filet).

Choix par défaut : Defender gardé mais bridé, OneDrive gardé tel quel, impression gardée,
mises à jour Windows en manuel depuis le compagnon.
"""

import json
import subprocess
import time
from pathlib import Path

from . import control, vm
from .i18n import N_, _

SCRIPT = Path(__file__).resolve().parent / "guest" / "slim.ps1"
SNAPSHOT = "avant-allegement"
CACHE = vm.DATA / "slim.json"  # dernier état lu, et mesure d'avant le premier allègement
# niveau 4 : hors des niveaux proposés dans le compagnon (Defender coupé), à choisir élément par élément
LEVELS = {1: N_("Léger"), 2: N_("Fort"), 3: N_("Maximal"), 4: N_("Sans antivirus"),
          5: N_("Ultra (Office et Power BI seuls)")}
GROUPS = {
    "telemetry": N_("Télémétrie et publicité"),
    "apps": N_("Applications"),
    "services": N_("Services"),
    "tasks": N_("Tâches planifiées"),
    "perf": N_("Mémoire et processeur"),
    "components": N_("Composants Windows"),
}

HKLM_POL = r"HKLM:\SOFTWARE\Policies\Microsoft"
HKCU_POL = r"HKCU:\Software\Policies\Microsoft"
CDM = r"HKCU:\Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager"


def _dw(path, name, value):
    return {"path": path, "name": name, "type": "DWord", "value": value}


def _svc(start, *names):
    """start : 3 manuel, 4 désactivé. « X_* » = modèle d'un service par utilisateur."""
    return [{"name": n, "start": start} for n in names]


# Chaque élément : key, group, level, title, subtitle, reversible (défaut vrai), puis le travail
# (svc, reg, task, appx, cap, feat, ps) décrit dans guest/slim.ps1.
CATALOG = [
    # -- télémétrie --
    {"key": "telemetry", "group": "telemetry", "level": 1,
     "title": N_("Données de diagnostic au minimum"),
     "subtitle": N_("Stratégie AllowTelemetry à 0 (Windows Pro la traite comme « requises »), service DiagTrack et envoi WAP arrêtés"),
     "reg": [_dw(fr"{HKLM_POL}\Windows\DataCollection", "AllowTelemetry", 0),
             _dw(fr"{HKLM_POL}\Windows\DataCollection", "DoNotShowFeedbackNotifications", 1),
             _dw(fr"{HKLM_POL}\Windows\Windows Error Reporting", "Disabled", 1),
             _dw(r"HKCU:\Software\Microsoft\Siuf\Rules", "NumberOfSIUFInPeriod", 0)],
     "svc": _svc(4, "DiagTrack", "dmwappushservice")},
    {"key": "ads", "group": "telemetry", "level": 1,
     "title": N_("Publicité et suggestions"),
     "subtitle": N_("Identifiant publicitaire, expériences personnalisées, applications suggérées et installées "
                    "sans avertissement, astuces"),
     "reg": [_dw(fr"{HKLM_POL}\Windows\AdvertisingInfo", "DisabledByGroupPolicy", 1),
             _dw(r"HKCU:\Software\Microsoft\Windows\CurrentVersion\AdvertisingInfo", "Enabled", 0),
             _dw(r"HKCU:\Software\Microsoft\Windows\CurrentVersion\Privacy",
                 "TailoredExperiencesWithDiagnosticDataEnabled", 0),
             _dw(fr"{HKCU_POL}\Windows\CloudContent", "DisableTailoredExperiencesWithDiagnosticData", 1),
             _dw(fr"{HKLM_POL}\Windows\CloudContent", "DisableWindowsConsumerFeatures", 1),
             _dw(fr"{HKLM_POL}\Windows\CloudContent", "DisableSoftLanding", 1),
             *[_dw(CDM, n, 0) for n in (
                 "SilentInstalledAppsEnabled", "SystemPaneSuggestionsEnabled", "SoftLandingEnabled",
                 "PreInstalledAppsEnabled", "OemPreInstalledAppsEnabled", "RotatingLockScreenEnabled",
                 "SubscribedContent-338388Enabled", "SubscribedContent-338389Enabled",
                 "SubscribedContent-353694Enabled", "SubscribedContent-353696Enabled")],
             _dw(r"HKCU:\Software\Microsoft\Windows\CurrentVersion\UserProfileEngagement",
                 "ScoobeSystemSettingEnabled", 0)]},
    {"key": "activity", "group": "telemetry", "level": 1,
     "title": N_("Historique d'activité et saisie"),
     "subtitle": N_("L'historique d'activité et les données de frappe et d'écriture manuscrite ne sont plus envoyés"),
     "reg": [_dw(fr"{HKLM_POL}\Windows\System", n, 0)
             for n in ("EnableActivityFeed", "PublishUserActivities", "UploadUserActivities")] + [
             _dw(r"HKCU:\Software\Microsoft\InputPersonalization", "RestrictImplicitTextCollection", 1),
             _dw(r"HKCU:\Software\Microsoft\InputPersonalization", "RestrictImplicitInkCollection", 1),
             _dw(r"HKCU:\Software\Microsoft\Personalization\Settings", "AcceptedPrivacyPolicy", 0)]},
    {"key": "search-web", "group": "telemetry", "level": 1,
     "title": N_("Bing, Copilot et Recall"),
     "subtitle": N_("Recherche Windows limitée à l'ordinateur ; Copilot, Recall et Click to Do désactivés"),
     "reg": [_dw(fr"{HKCU_POL}\Windows\Explorer", "DisableSearchBoxSuggestions", 1),
             _dw(fr"{HKLM_POL}\Windows\Windows Search", "AllowCortana", 0),
             _dw(fr"{HKLM_POL}\Windows\Windows Search", "ConnectedSearchUseWeb", 0),
             _dw(fr"{HKLM_POL}\Windows\Windows Search", "DisableWebSearch", 1),
             _dw(fr"{HKCU_POL}\Windows\WindowsCopilot", "TurnOffWindowsCopilot", 1),
             _dw(fr"{HKLM_POL}\Windows\WindowsAI", "DisableAIDataAnalysis", 1),
             _dw(fr"{HKLM_POL}\Windows\WindowsAI", "AllowRecallEnablement", 0),
             _dw(fr"{HKLM_POL}\Windows\WindowsAI", "DisableClickToDo", 1),
             _dw(fr"{HKLM_POL}\Dsh", "AllowNewsAndInterests", 0)]},
    {"key": "office-telemetry", "group": "telemetry", "level": 1,
     "title": N_("Télémétrie d'Office"),
     "subtitle": N_("Envoi de données, enquêtes et expériences connectées facultatives désactivés ; la coédition et "
                    "SharePoint restent disponibles"),
     "reg": [_dw(fr"{HKCU_POL}\office\common\clienttelemetry", "SendTelemetry", 3),
             _dw(fr"{HKCU_POL}\office\16.0\common\privacy", "controllerconnectedservicesenabled", 2),
             _dw(fr"{HKCU_POL}\office\16.0\common\feedback", "enabled", 0),
             _dw(fr"{HKCU_POL}\office\16.0\common\feedback", "surveyenabled", 0)]},
    {"key": "edge", "group": "telemetry", "level": 1,
     "title": N_("Edge en arrière-plan"),
     "subtitle": N_("Démarrage anticipé, mode arrière-plan, données de diagnostic et barre latérale désactivés ; "
                    "WebView2 (Outlook, Teams) n'est pas modifié"),
     "reg": [_dw(fr"{HKLM_POL}\Edge", "StartupBoostEnabled", 0),
             _dw(fr"{HKLM_POL}\Edge", "BackgroundModeEnabled", 0),
             _dw(fr"{HKLM_POL}\Edge", "DiagnosticData", 0),
             _dw(fr"{HKLM_POL}\Edge", "PersonalizationReportingEnabled", 0),
             _dw(fr"{HKLM_POL}\Edge", "HubsSidebarEnabled", 0)],
     # entrée Run « MicrosoftEdgeAutoLaunch_<hash> » : gardée pour la restauration
     "ps": {
         "test": r"-not (Get-ItemProperty HKCU:\Software\Microsoft\Windows\CurrentVersion\Run).PSObject.Properties.Name.Where({$_ -like 'MicrosoftEdgeAutoLaunch*'})",
         "apply": r"""
$k = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$p = (Get-ItemProperty $k).PSObject.Properties | Where-Object Name -like 'MicrosoftEdgeAutoLaunch*'
$p | ForEach-Object { Remove-ItemProperty $k -Name $_.Name }
($p | ForEach-Object { $_.Name + '=' + $_.Value }) -join "`n"
""",
         "restore": r"""
param($B)
foreach ($l in ($B -split "`n")) { if ($l) { $i = $l.IndexOf('='); New-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name $l.Substring(0, $i) -Value $l.Substring($i + 1) -Force | Out-Null } }
"""}},

    # -- applications --
    {"key": "apps-consumer", "group": "apps", "level": 1, "reversible": False,
     "title": N_("Applications grand public"),
     "subtitle": N_("Clipchamp, Actualités, Météo, Bing, Xbox et jeux, Solitaire, Aide, Hub de commentaires, "
                    "Dev Home, Power Automate, compagnons M365, Assistance rapide, Media Player"),
     "appx": ["Clipchamp.Clipchamp", "Microsoft.BingNews", "Microsoft.BingWeather", "Microsoft.BingSearch",
              "Microsoft.GamingApp", "Microsoft.Xbox.TCUI", "Microsoft.XboxGamingOverlay",
              "Microsoft.XboxIdentityProvider", "Microsoft.XboxSpeechToTextOverlay",
              "Microsoft.MicrosoftSolitaireCollection", "Microsoft.GetHelp", "Microsoft.WindowsFeedbackHub",
              "Microsoft.Windows.DevHome", "Microsoft.PowerAutomateDesktop", "Microsoft.M365Companions",
              "MicrosoftCorporationII.QuickAssist", "Microsoft.ZuneMusic"]},
    {"key": "apps-extra", "group": "apps", "level": 2, "reversible": False,
     "title": N_("Petites applications Windows"),
     "subtitle": N_("To Do, Alarmes, Caméra, Enregistreur vocal, Pense-bêtes, Photos, Mobile connecté (Phone Link), "
                    "Widgets, gestionnaire IA ; conservées : Bloc-notes, Calculatrice, Paint, Capture, Terminal, "
                    "Store"),
     "appx": ["Microsoft.Todos", "Microsoft.WindowsAlarms", "Microsoft.WindowsCamera",
              "Microsoft.WindowsSoundRecorder", "Microsoft.MicrosoftStickyNotes", "Microsoft.Windows.Photos",
              "Microsoft.YourPhone", "MicrosoftWindows.CrossDevice", "MicrosoftWindows.Client.WebExperience",
              "aimgr"]},

    # -- services --
    {"key": "svc-light", "group": "services", "level": 2,
     "title": N_("Services sans usage dans la VM"),
     "subtitle": N_("Géolocalisation, liens distribués, radios, cartes, Xbox, appareils connectés, synchronisation "
                    "Courrier/Contacts, compatibilité des programmes, inventaire, luminosité, MIDI, IA Windows"),
     "svc": _svc(4, "lfsvc", "TrkWks", "RmSvc", "MapsBroker", "XblAuthManager", "XblGameSave",
                 "XboxNetApiSvc", "XboxGipSvc", "CDPSvc", "CDPUserSvc_*", "OneSyncSvc_*", "PcaSvc",
                 "InventorySvc", "DisplayEnhancementService", "midisrv", "WSAIFabricSvc", "whesvc",
                 "iphlpsvc", "lmhosts", "SstpSvc", "WerSvc")},
    {"key": "sysmain", "group": "services", "level": 2,
     "title": N_("Préchargement (SysMain)"),
     "subtitle": N_("Windows ne précharge plus en mémoire les applications qu'il prévoit d'ouvrir : inutile sur "
                    "un disque virtuel. Le service SysMain reste actif, la compression de la mémoire en dépend"),
     # pas SysMain désactivé : la compression de la mémoire (memcomp) en dépend, et Windows le
     # remettait en automatique à chaque démarrage
     "reg": [_dw(r"HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PrefetchParameters",
                 n, 0) for n in ("EnablePrefetcher", "EnableSuperfetch")]},
    {"key": "wsearch", "group": "services", "level": 2,
     "title": N_("Indexation (Windows Search)"),
     "subtitle": N_("Le nouvel Outlook effectue ses recherches sur le serveur ; la recherche de fichiers depuis le "
                    "menu Démarrer devient plus lente"),
     "svc": _svc(4, "WSearch")},
    {"key": "svc-heavy", "group": "services", "level": 3,
     "title": N_("Partage de fichiers entrant et diagnostic"),
     "subtitle": N_("Serveur SMB (les dossiers passent par virtiofs) et service de stratégie de diagnostic (dépannage réseau)"),
     "svc": _svc(4, "LanmanServer", "DPS", "WdiServiceHost", "WdiSystemHost")},
    {"key": "updates", "group": "services", "level": 1,
     "title": N_("Mises à jour de Windows manuelles"),
     "subtitle": N_("Windows n'installe plus les mises à jour en arrière-plan et n'impose plus de redémarrage ; "
                    "bouton « Mettre à jour Windows » plus bas. Les mises à jour du Store et d'Office restent "
                    "automatiques ; pas de partage des mises à jour en pair à pair"),
     "reg": [_dw(fr"{HKLM_POL}\Windows\WindowsUpdate\AU", "NoAutoUpdate", 1),
             _dw(fr"{HKLM_POL}\Windows\WindowsUpdate\AU", "AUOptions", 2),
             _dw(fr"{HKLM_POL}\Windows\WindowsUpdate\AU", "NoAutoRebootWithLoggedOnUsers", 1),
             _dw(fr"{HKLM_POL}\Windows\DeliveryOptimization", "DODownloadMode", 0)]},

    # -- tâches planifiées --
    {"key": "tasks-telemetry", "group": "tasks", "level": 1,
     "title": N_("Tâches de collecte"),
     "subtitle": N_("Programme d'amélioration, évaluation de compatibilité, diagnostic disque, commentaires, rapports d'erreurs"),
     "task": [r"\Microsoft\Windows\Application Experience\*",
              r"\Microsoft\Windows\Customer Experience Improvement Program\*",
              r"\Microsoft\Windows\Autochk\Proxy",
              r"\Microsoft\Windows\DiskDiagnostic\Microsoft-Windows-DiskDiagnosticDataCollector",
              r"\Microsoft\Windows\Feedback\Siuf\*",
              r"\Microsoft\Windows\Windows Error Reporting\QueueReporting",
              r"\Microsoft\Windows\Maps\*",
              r"\Microsoft\Windows\Power Efficiency Diagnostics\AnalyzeSystem",
              r"\Microsoft\XblGameSave\XblGameSaveTask"]},
    {"key": "tasks-extra", "group": "tasks", "level": 3,
     "title": N_("Tâches de fond secondaires"),
     "subtitle": N_("IA Windows (Recall, Click to Do), modèles vocaux, prévisions du réseau électrique, essais de "
                    "fonctions, inventaire de l'appareil, suggestions, rapports OneDrive, vérification horaire d'Edge "
                    "(la quotidienne reste : WebView2 continue de se mettre à jour), déploiement des nouvelles "
                    "fonctions et moniteur de performances d'Office (les mises à jour d'Office restent "
                    "automatiques)"),
     "task": [r"\Microsoft\Windows\WindowsAI\*\*",
              r"\Microsoft\Windows\Speech\SpeechModelDownloadTask",
              r"\Microsoft\Windows\Sustainability\*",
              r"\Microsoft\Windows\Flighting\*\*",
              r"\Microsoft\Windows\UsageAndQualityInsights\*",
              r"\Microsoft\Windows\Device Information\*",
              r"\SoftLanding\*\*",
              r"\OneDrive Reporting Task-*",
              r"\MicrosoftEdgeUpdateTaskMachineUA*",
              r"\Microsoft\Office\Office Feature Updates*",
              r"\Microsoft\Office\Office Performance Monitor",
              r"\Microsoft\Office\Office Background Push Maintenance"]},
    {"key": "maintenance", "group": "tasks", "level": 3,
     "title": N_("Maintenance automatique"),
     "subtitle": N_("Défragmentation planifiée et maintenance de nuit désactivées (le disque virtuel reçoit déjà les "
                    "TRIM)"),
     "task": [r"\Microsoft\Windows\Defrag\ScheduledDefrag"],
     "reg": [_dw(r"HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Schedule\Maintenance",
                 "MaintenanceDisabled", 1)]},

    # -- mémoire et processeur --
    {"key": "defender", "group": "perf", "level": 2,
     "title": N_("Defender limité"),
     "subtitle": N_("Protection en temps réel conservée ; analyses limitées à 20 % du processeur, en priorité basse, "
                    "uniquement lorsque Windows est inactif ; agent Vasistas exclu"),
     "ps": {
         "test": r"$m = Get-MpPreference; $m.ScanAvgCPULoadFactor -eq 20 -and $m.EnableLowCpuPriority -and $m.ScanOnlyIfIdleEnabled",
         "apply": r"""
$m = Get-MpPreference
"$($m.ScanAvgCPULoadFactor);$([int]$m.EnableLowCpuPriority);$([int]$m.ScanOnlyIfIdleEnabled);$([int]$m.DisableCatchupFullScan)"
Set-MpPreference -ScanAvgCPULoadFactor 20 -EnableLowCpuPriority $true -ScanOnlyIfIdleEnabled $true -DisableCatchupFullScan $true
Add-MpPreference -ExclusionProcess 'Vasistas.Agent.exe' -ExclusionPath 'C:\Program Files\Vasistas'
""",
         "restore": r"""
param($B)
$v = $B -split ';'
Set-MpPreference -ScanAvgCPULoadFactor ([int]$v[0]) -EnableLowCpuPriority ([bool][int]$v[1]) -ScanOnlyIfIdleEnabled ([bool][int]$v[2]) -DisableCatchupFullScan ([bool][int]$v[3])
Remove-MpPreference -ExclusionProcess 'Vasistas.Agent.exe' -ExclusionPath 'C:\Program Files\Vasistas'
"""}},
    {"key": "defender-off", "group": "perf", "level": 4,
     "title": N_("Defender coupé"),
     "subtitle": N_("Protection en temps réel, surveillance des comportements et analyse à l'accès désactivées : "
                    "Windows n'analyse plus les pièces jointes ni les documents téléchargés. Demande d'abord de "
                    "couper la protection contre les falsifications dans Sécurité Windows"),
     "ps": {
         "test": r"(Get-MpComputerStatus).RealTimeProtectionEnabled -eq $false",
         "apply": r"""
if ((Get-MpComputerStatus).IsTamperProtected) {
    throw 'protection contre les falsifications active : la couper dans Sécurité Windows > Protection contre les virus et menaces > Gérer les paramètres, puis réappliquer'
}
$k = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows Defender\Real-Time Protection'
New-Item $k -Force | Out-Null
foreach ($n in 'DisableRealtimeMonitoring', 'DisableBehaviorMonitoring', 'DisableOnAccessProtection', 'DisableScanOnRealtimeEnable', 'DisableIOAVProtection') {
    Set-ItemProperty $k $n 1 -Type DWord
}
Set-MpPreference -DisableRealtimeMonitoring $true -DisableBehaviorMonitoring $true -DisableIOAVProtection $true
""",
         "restore": r"""
param($B)
Remove-Item 'HKLM:\SOFTWARE\Policies\Microsoft\Windows Defender\Real-Time Protection' -Recurse -ErrorAction SilentlyContinue
Set-MpPreference -DisableRealtimeMonitoring $false -DisableBehaviorMonitoring $false -DisableIOAVProtection $false
"""}},
    {"key": "uac-silent", "group": "perf", "level": 4,
     "title": N_("Élévation sans confirmation"),
     "subtitle": N_("Les programmes qui demandent les droits d'administrateur les obtiennent sans fenêtre de "
                    "contrôle de compte : Windows refuse les clics transmis par Vasistas dans ces fenêtres, qui "
                    "restaient bloquées"),
     "reg": [_dw(r"HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System",
                 "ConsentPromptBehaviorAdmin", 0)]},
    {"key": "background", "group": "perf", "level": 2,
     "title": N_("Applications en arrière-plan"),
     "subtitle": N_("Les applications du Store ne fonctionnent plus une fois leur fenêtre fermée, sauf Teams et "
                    "Outlook (notifications)"),
     "reg": [_dw(fr"{HKLM_POL}\Windows\AppPrivacy", "LetAppsRunInBackground", 2),
             {"path": fr"{HKLM_POL}\Windows\AppPrivacy", "name": "LetAppsRunInBackground_ForceAllowTheseApps",
              "type": "MultiString",
              "value": ["MSTeams_8wekyb3d8bbwe", "Microsoft.OutlookForWindows_8wekyb3d8bbwe"]}]},
    {"key": "tray", "group": "perf", "level": 2,
     "title": N_("Icône Sécurité Windows au démarrage"),
     "subtitle": N_("La barre des tâches est masquée : l'icône est inutile (Defender reste actif)"),
     "ps": {
         "test": r"-not (Get-ItemProperty HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run).SecurityHealth",
         "apply": r"""
$k = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run'
$v = (Get-ItemProperty $k).SecurityHealth
if ($v) { Remove-ItemProperty $k -Name SecurityHealth; $v }
""",
         "restore": r"""
param($B)
if ($B) { New-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run' -Name SecurityHealth -PropertyType ExpandString -Value $B -Force | Out-Null }
"""}},
    {"key": "hibernate", "group": "perf", "level": 2,
     "title": N_("Veille prolongée et démarrage rapide"),
     "subtitle": N_("Inutiles, car Vasistas met lui-même la VM en pause ; l'espace du fichier hiberfil.sys est "
                    "libéré"),
     "ps": {"test": r"-not (Test-Path C:\hiberfil.sys -ErrorAction SilentlyContinue)",
            "apply": "powercfg /hibernate off | Out-Null",
            "restore": "powercfg /hibernate on | Out-Null"}},
    {"key": "pagefile", "group": "perf", "level": 3,
     "title": N_("Fichier d'échange de 4 à 16 Go"),
     "subtitle": N_("Taille réglée à la main au lieu de la gestion automatique de Windows ; au-dessous de 16 Go, "
                    "Power BI manque de mémoire (prend effet au redémarrage)"),
     "ps": {
         "test": r"$p = Get-CimInstance Win32_PageFileSetting; $p -and $p.InitialSize -eq 4096 -and $p.MaximumSize -eq 16384",
         "apply": r"""
$cs = Get-CimInstance Win32_ComputerSystem
[string]$cs.AutomaticManagedPagefile
Set-CimInstance $cs -Property @{ AutomaticManagedPagefile = $false }
$p = Get-CimInstance Win32_PageFileSetting
if (-not $p) { $p = New-CimInstance Win32_PageFileSetting -Property @{ Name = 'C:\pagefile.sys' } }
Set-CimInstance $p -Property @{ InitialSize = [uint32]4096; MaximumSize = [uint32]16384 }
""",
         "restore": r"""
param($B)
if ($B -eq 'True') { Set-CimInstance (Get-CimInstance Win32_ComputerSystem) -Property @{ AutomaticManagedPagefile = $true } }
"""}},

    {"key": "memcomp", "group": "perf", "level": 2,
     "title": N_("Compression de la mémoire"),
     "subtitle": N_("Windows compresse la mémoire peu utilisée au lieu de l'écrire sur disque : moins de RAM "
                    "occupée, et le ballon en rend davantage à Linux"),
     "ps": {"test": "(Get-MMAgent).MemoryCompression",
            "apply": "Enable-MMAgent -MemoryCompression",
            "restore": "Disable-MMAgent -MemoryCompression"}},
    {"key": "svc-sober", "group": "services", "level": 3,
     "title": N_("Services rarement utiles"),
     "subtitle": N_("Transferts en arrière-plan (BITS) et WebDAV démarrés à la demande seulement ; consommation "
                    "de données, programme Insider, contrôle parental, mode démo et télécopie désactivés"),
     "svc": _svc(3, "BITS", "WebClient") + _svc(4, "DusmSvc", "wisvc", "WpcMonSvc", "RetailDemo", "Fax")},
    {"key": "cd-polling", "group": "perf", "level": 2,
     "title": N_("Surveillance des lecteurs CD"),
     "subtitle": N_("Windows ne vérifie plus en continu si un disque a été inséré : chaque vérification réveillait "
                    "la VM (prend effet au redémarrage)"),
     "reg": [_dw(r"HKLM:\SYSTEM\CurrentControlSet\Services\cdrom", "AutoRun", 0)]},
    {"key": "onedrive", "group": "apps", "level": 3, "reversible": False,
     "title": N_("OneDrive dans Windows"),
     "subtitle": N_("Client de synchronisation désinstallé et bloqué : les documents arrivent par les dossiers "
                    "partagés de Linux ; Office enregistre toujours dans OneDrive et SharePoint"),
     "reg": [_dw(fr"{HKLM_POL}\Windows\OneDrive", "DisableFileSyncNGSC", 1)],
     "task": [r"\OneDrive *"],
     "ps": {
         "test": r"-not (Test-Path 'C:\Program Files\Microsoft OneDrive\OneDrive.exe') -and -not (Test-Path (Join-Path $env:LOCALAPPDATA 'Microsoft\OneDrive\OneDrive.exe'))",
         "apply": r"""
Get-Process OneDrive -ErrorAction SilentlyContinue | Stop-Process -Force
$setup = @(Get-ChildItem 'C:\Program Files\Microsoft OneDrive\*\OneDriveSetup.exe', "$env:LOCALAPPDATA\Microsoft\OneDrive\*\OneDriveSetup.exe" -ErrorAction SilentlyContinue) + @(Get-Item "$env:SystemRoot\System32\OneDriveSetup.exe" -ErrorAction SilentlyContinue)
foreach ($s in $setup) { Start-Process $s.FullName '/uninstall /allusers' -Wait -ErrorAction SilentlyContinue; if (-not (Test-Path 'C:\Program Files\Microsoft OneDrive\OneDrive.exe')) { break } }
foreach ($k in 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run', 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run') {
    foreach ($n in 'OneDrive', 'OneDriveSetup') { Remove-ItemProperty $k -Name $n -ErrorAction SilentlyContinue }
}
"""}},
    {"key": "svc-extra", "group": "services", "level": 2,
     "title": N_("Découverte réseau et BitLocker"),
     "subtitle": N_("Découverte UPnP (SSDP) et service BitLocker : ni l'un ni l'autre ne servent dans la VM"),
     "svc": _svc(4, "SSDPSRV", "upnphost", "BDESVC", "FDResPub", "fdPHost")},
    {"key": "apps-teams", "group": "apps", "level": 2, "reversible": False,
     "title": N_("Teams dans Windows"),
     "subtitle": N_("Doublon de Teams sous Linux (Microsoft 365 en ligne)"),
     "appx": ["MSTeams"]},

    # -- niveau Ultra : tout ce qu'Office et Power BI n'utilisent pas. Gardés exprès : capture
    # d'écran (CaptureService, l'agent filme par WGC), notifications (WpnService, bulles d'Outlook),
    # comptes (TokenBroker, wlidsvc, ClipSVC), impression, WebView2, horloge, polices, thèmes --
    {"key": "svc-ultra", "group": "services", "level": 5,
     "title": N_("Services sans usage pour Office et Power BI"),
     "subtitle": N_("Bureau à distance, capteurs, Bluetooth, carte à puce, biométrie, scanner, téléphonie, "
                    "fichiers hors connexion, partage de connexion, Wi-Fi Direct, réalité mixte, lecture en "
                    "cours, contacts et messages Windows, optimisation de la distribution, exécution sous un "
                    "autre compte, filtrage web de Defender"),
     "svc": _svc(4, "TermService", "SessionEnv", "UmRdpService", "RemoteRegistry", "RemoteAccess", "RpcLocator",
                 "SensorService", "SensorDataService", "SensrSvc", "bthserv", "BthAvctpSvc", "BTAGService",
                 "SCardSvr", "ScDeviceEnum", "SCPolicySvc", "WbioSrvc", "NaturalAuthentication", "stisvc",
                 "FrameServer", "FrameServerMonitor", "TapiSrv", "PhoneSvc", "SmsRouter", "CscService",
                 "SharedAccess", "icssvc", "WFDSConMgrSvc", "lltdsvc", "MSiSCSI", "NetTcpPortSharing",
                 "p2pimsvc", "p2psvc", "PNRPsvc", "PeerDistSvc", "QWAVE", "SNMPTrap", "SEMgrSvc",
                 "WalletService", "spectrum", "SharedRealitySvc", "MixedRealityOpenXRSvc",
                 "perceptionsimulation", "WMPNetworkSvc", "workfolderssvc", "AssignedAccessManagerSvc",
                 "AJRouter", "ALG", "dmwappushservice", "wercplsupport", "autotimesvc", "AxInstSV",
                 "seclogon", "DoSvc", "webthreatdefsvc", "webthreatdefusersvc_*", "NPSMSvc_*",
                 "BcastDVRUserService_*", "MessagingService_*", "PimIndexMaintenanceSvc_*",
                 "BluetoothUserService_*", "DevicePickerUserSvc_*", "MicrosoftEdgeElevationService")},
    {"key": "tasks-ultra", "group": "tasks", "level": 5,
     "title": N_("Tâches d'entretien de Windows"),
     "subtitle": N_("Diagnostics, vérification du disque et de la mémoire, sauvegarde du registre, nettoyage des "
                    "composants, notes de performance, emplacement, réseau mobile, fichiers hors connexion, "
                    "Bluetooth, analyses planifiées de Defender ; les tâches de licence et de mise à jour "
                    "d'Office et du Store restent actives"),
     "task": [r"\Microsoft\Windows\CloudExperienceHost\*",
              r"\Microsoft\Windows\Chkdsk\*",
              r"\Microsoft\Windows\Data Integrity Scan\*",
              r"\Microsoft\Windows\Diagnosis\*",
              r"\Microsoft\Windows\DiskFootprint\*",
              r"\Microsoft\Windows\FileHistory\*",
              r"\Microsoft\Windows\Location\*",
              r"\Microsoft\Windows\Maintenance\WinSAT",
              r"\Microsoft\Windows\MemoryDiagnostic\*",
              r"\Microsoft\Windows\Mobile Broadband Accounts\*",
              r"\Microsoft\Windows\NetTrace\*",
              r"\Microsoft\Windows\Offline Files\*",
              r"\Microsoft\Windows\PI\*",
              r"\Microsoft\Windows\Registry\RegIdleBackup",
              r"\Microsoft\Windows\RetailDemo\*",
              r"\Microsoft\Windows\Servicing\StartComponentCleanup",
              r"\Microsoft\Windows\Shell\FamilySafety*",
              r"\Microsoft\Windows\SpacePort\*",
              r"\Microsoft\Windows\WDI\*",
              r"\Microsoft\Windows\Windows Defender\*",
              r"\Microsoft\Windows\Work Folders\*",
              r"\Microsoft\Windows\WwanSvc\*",
              r"\Microsoft\Windows\Bluetooth\*",
              r"\Microsoft\Windows\HelloFace\*",
              r"\Microsoft\Windows\StateRepository\*"]},
    {"key": "autologgers", "group": "perf", "level": 5,
     "title": N_("Journaux de suivi au démarrage"),
     "subtitle": N_("Sessions de traçage que Windows ouvre à chaque démarrage pour la télémétrie, le Wi-Fi, "
                    "Defender, le réseau et le disque ; les journaux d'événements restent (prend effet au "
                    "redémarrage)"),
     "reg": [_dw(rf"HKLM:\SYSTEM\CurrentControlSet\Control\WMI\Autologger\{n}", "Start", 0)
             for n in ("Diagtrack-Listener", "SQMLogger", "CloudExperienceHostOobe", "ReadyBoot", "WiFiSession",
                       "LwtNetLog", "NBSMBLOGGER", "NtfsLog",
                       "PEAuthLog", "RdrLog", "WdiContextLog", "Mellanox-Kernel")]},

    # -- composants --
    {"key": "caps", "group": "components", "level": 3, "reversible": False,
     "title": N_("Composants facultatifs"),
     "subtitle": N_("Pilotes Wi-Fi et Ethernet physiques, Windows Hello visage, Internet Explorer, enregistreur "
                    "d'actions, reconnaissance d'écriture, de maths, de la parole et OCR, PowerShell ISE, Lecteur "
                    "Windows Media, fonds d'écran ; la synthèse vocale (Lecture à voix haute de Word) est conservée"),
     "cap": ["Microsoft.Windows.Wifi.Client.", "Microsoft.Windows.Ethernet.Client.", "Hello.Face.",
             "Browser.InternetExplorer~", "App.StepsRecorder~", "MathRecognizer~", "Language.Handwriting~",
             "Language.Speech~", "Language.OCR~", "Microsoft.Windows.PowerShell.ISE~",
             "Media.WindowsMediaPlayer~", "Microsoft.Wallpapers.Extended~"]},
    {"key": "features", "group": "components", "level": 3,
     "title": N_("Fonctionnalités facultatives"),
     "subtitle": N_("Dossiers de travail, SMB Direct, impression Internet, Lecteur Windows Media hérité ; Microsoft "
                    "Print to PDF est conservé"),
     "feat": ["WorkFolders-Client", "SmbDirect", "Printing-Foundation-InternetPrinting-Client",
              "WindowsMediaPlayer", "MediaPlayback"]},
]
BY_KEY = {it["key"]: it for it in CATALOG}


def _plan(action, keys):
    items = []
    for k in keys:
        it = {x: v for x, v in BY_KEY[k].items()
              if x in ("key", "svc", "reg", "task", "appx", "cap", "feat", "ps")}
        items.append(it)
    return json.dumps({"action": action, "items": items}, ensure_ascii=True)


def run(action, keys=None, timeout=None):
    """Envoie le moteur à l'invité ; renvoie son JSON (status, errors, reboot, ram_used_mb...)."""
    keys = list(keys or BY_KEY)
    plan = _plan(action, keys).replace("'", "''")
    script = f"$Plan = '{plan}'\n" + SCRIPT.read_text(encoding="utf-8")
    res = control.request({"exec": script}, timeout=timeout)
    if res.get("error"):
        raise RuntimeError(res["error"])
    out = (res.get("out") or "").strip()
    last = out.splitlines()[-1] if out else ""
    try:
        result = json.loads(last)
    except ValueError:
        raise RuntimeError(out[-2000:] or f"code {res.get('code')}") from None
    _remember(action, result)
    return result


def _measure(r):
    return {k: r.get(k) for k in ("ram_used_mb", "processes", "services")} | {"time": int(time.time())}


def _remember(action, result):
    c = cached()
    if action == "status" and not c.get("baseline") and not result.get("backup"):
        c["baseline"] = _measure(result)
    c["status"] = {**c.get("status", {}), **result.get("status", {})}
    c["last"] = _measure(result)
    CACHE.write_text(json.dumps(c, ensure_ascii=False, indent=1))


def cached():
    try:
        return json.loads(CACHE.read_text())
    except (OSError, ValueError):
        return {}


def status():
    return run("status", timeout=300)


def apply(keys):
    # suppression de composants : plusieurs minutes chacun
    return run("apply", keys, timeout=None)


def restore(keys):
    return run("restore", [k for k in keys if BY_KEY[k].get("reversible", True)], timeout=None)


KEEP_UP_S = 20 * 3600


def drifted(before, now):
    """Éléments allégés (« on ») que Windows a défaits depuis (mise à jour, réparation)."""
    return sorted(k for k, v in before.items() if v == "on" and now.get(k) in ("partial", "off") and k in BY_KEY)


def keep_up():
    """Réapplique ce que Windows a défait ; au plus une fois par période KEEP_UP_S. Appelé par
    l'hôte quand Windows est prêt, hors du fil GTK (le moteur passe par le socket de contrôle)."""
    c = cached()
    before = c.get("status", {})
    if not any(v == "on" for v in before.values()) or time.time() - c.get("kept_up", 0) < KEEP_UP_S:
        return []
    keys = drifted(before, status().get("status", {}))
    if keys:
        try:
            apply(keys)
        except Exception:
            # status() vient d'écrire « partial » : remettre « on » pour réessayer au prochain démarrage
            c = cached()
            c.setdefault("status", {}).update({k: "on" for k in keys})
            CACHE.write_text(json.dumps(c, ensure_ascii=False, indent=1))
            raise
    c = cached()
    c["kept_up"] = int(time.time())
    CACHE.write_text(json.dumps(c, ensure_ascii=False, indent=1))
    return keys


def keys_for_level(level):
    return [it["key"] for it in CATALOG if it["level"] <= level]


# -- instantané du disque (filet avant les suppressions définitives) --

def _qmp(command, **args):
    # pas q.cmd(...) : ses propres paramètres s'appellent « name », comme celui de l'instantané
    q = vm.Qmp(timeout=600)  # voir restore._qmp
    try:
        q.file.write(json.dumps({"execute": command, "arguments": args}).encode() + b"\n")
        q.file.flush()
        reply = q._read()
        if "error" in reply:
            raise RuntimeError(reply["error"].get("desc"))
        return reply.get("return")
    finally:
        q.close()


def snapshots():
    out = subprocess.run([vm.QEMU_IMG, "snapshot", "-l", "-U", str(vm.DISK)],
                         capture_output=True, text=True).stdout
    return [line.split()[1] for line in out.splitlines()[2:] if len(line.split()) > 1]


def snapshot():
    """Instantané interne du disque, VM allumée (QMP) ou éteinte (qemu-img).
    VM allumée : cohérent comme après une coupure de courant, suffisant pour revenir en arrière."""
    if SNAPSHOT in snapshots():
        return False
    if vm.pid():
        _qmp("blockdev-snapshot-internal-sync", device="disk", name=SNAPSHOT)
    else:
        subprocess.run([vm.QEMU_IMG, "snapshot", "-c", SNAPSHOT, str(vm.DISK)], check=True)
    return True


def rollback():
    """Revient à l'instantané : VM arrêtée obligatoire."""
    if vm.pid():
        raise RuntimeError(_("arrêtez d'abord Windows"))
    subprocess.run([vm.QEMU_IMG, "snapshot", "-a", SNAPSHOT, str(vm.DISK)], check=True)


def drop_snapshot():
    if vm.pid():
        _qmp("blockdev-snapshot-delete-internal-sync", device="disk", name=SNAPSHOT)
    else:
        subprocess.run([vm.QEMU_IMG, "snapshot", "-d", SNAPSHOT, str(vm.DISK)], check=True)


def open_windows_update():
    control.request({"exec": "Start-Process 'ms-settings:windowsupdate-action'"}, timeout=30)
    cfg = vm.load_config()
    cfg["last_windows_update"] = int(time.time())
    vm.save_config(cfg)
