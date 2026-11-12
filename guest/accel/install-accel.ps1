# Vasistas Beta : installe le pilote graphique accel-virt dans Windows (lancé par l'agent, en
# administrateur, par `vasistas accel install`). Le paquet arrive sur le CD de partage de
# Vasistas, dossier av\ (provision.ps1 et package\ d'accel-virt, adapters.txt de Vasistas).
#
# 1. copie dans C:\av, où provision.ps1 l'attend ;
# 2. pilotes graphiques jamais pris sur Windows Update : la carte se présente avec les
#    identifiants de la carte de l'hôte (AMD, NVIDIA), et le vrai pilote du fabricant y fait un
#    écran bleu. Seules les recherches de pilotes sont coupées : Windows Update reste actif,
#    contrairement à l'étape « prepare » d'accel-virt, que Vasistas n'utilise pas ;
# 3. provision.ps1 sign (certificat de test, catalogue, signature de test activée),
#    install -NoVerifier, puis check.
# Une ligne « accel: <étape> <résultat> » par étape, pour l'hôte. Code 3010 : redémarrer.
param([switch]$Remove)
$ErrorActionPreference = 'Stop'

function Step($Name, $Value) { Write-Output "accel: $Name $Value" }

function SetDword($Path, $Name, $Value) {
    if (-not (Test-Path $Path)) { New-Item -Path $Path -Force | Out-Null }
    New-ItemProperty -Path $Path -Name $Name -Value $Value -PropertyType DWord -Force | Out-Null
}

if ($Remove) {
    # retour à l'affichage habituel : le pilote quitte le magasin de pilotes ; la signature
    # de test reste (le pilote maison de Vasistas peut en dépendre)
    foreach ($line in (pnputil /enum-drivers | Out-String) -split "`r?`n`r?`n") {
        if ($line -match 'avgpu\.inf' -and $line -match '(oem\d+\.inf)') {
            pnputil /delete-driver $Matches[1] /uninstall /force | Out-Null
            Step 'remove' $Matches[1]
        }
    }
    exit 0
}

$cd = Get-PSDrive -PSProvider FileSystem | Where-Object { Test-Path (Join-Path $_.Root 'vasistas.tag') } |
    Select-Object -First 1
if (-not $cd) { Step 'source' 'absent'; exit 1 }
$source = Join-Path $cd.Root 'av'
if (-not (Test-Path (Join-Path $source 'package\avgpu.sys'))) { Step 'source' 'incomplete'; exit 1 }
New-Item -ItemType Directory -Path 'C:\av' -Force | Out-Null
Remove-Item 'C:\av\package' -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item (Join-Path $source '*') 'C:\av' -Recurse -Force
# le CD est en lecture seule : les copies le restent, provision.ps1 réécrit l'INF
Get-ChildItem 'C:\av' -Recurse -File | ForEach-Object { $_.IsReadOnly = $false }
Step 'copy' 'ok'

SetDword 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate' ExcludeWUDriversInQualityUpdate 1
SetDword 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\DriverSearching' DontSearchWindowsUpdate 1
SetDword 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching' SearchOrderConfig 0
SetDword 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Device Metadata' PreventDeviceMetadataFromNetwork 1
Step 'driver-updates' 'off'

# Windows Update a pu poser le vrai pilote du fabricant avant ce script : signé par Microsoft, il
# est mieux classé que le nôtre et pnputil n'installe alors le paquet sur rien (code 259)
foreach ($line in Get-Content 'C:\av\adapters.txt') {
    $id = $line -split "`t"
    if ($id.Count -lt 2) { continue }
    foreach ($device in @(Get-PnpDevice -Class Display -ErrorAction SilentlyContinue |
            Where-Object { $_.InstanceId -like "PCI\VEN_$($id[0])&DEV_$($id[1])*" })) {
        $prop = { param($Key) (Get-PnpDeviceProperty -InstanceId $device.InstanceId -KeyName $Key).Data }
        $inf = & $prop DEVPKEY_Device_DriverInfPath
        if ($inf -like 'oem*.inf' -and (& $prop DEVPKEY_Device_DriverProvider) -ne 'accel-virt') {
            pnputil /delete-driver $inf /uninstall /force | Out-Null
            Step 'foreign-driver' "$inf removed"
        }
    }
}

$reboot = $false
# chaînes plutôt que tableaux imbriqués : PowerShell aplatit un tableau d'un seul élément
foreach ($stage in 'sign', 'install -NoVerifier', 'check') {
    $parts = $stage -split ' '
    $name = $parts[0]
    $argv = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', 'C:\av\provision.ps1', '-Stage') + $parts
    $out = & powershell.exe @argv 2>&1
    $code = $LASTEXITCODE
    $out | ForEach-Object { Write-Output "  $_" }
    if ($code -eq 3010) { $reboot = $true; Step $name 'reboot'; continue }
    if ($code -ne 0) {
        # avant le redémarrage, « check » ne peut pas voir le pilote démarré
        if ($name -eq 'check' -and $reboot) { Step $name 'after-reboot'; continue }
        Step $name "failed $code"; exit 1
    }
    Step $name 'ok'
}
if ($reboot) { exit 3010 }
exit 0
