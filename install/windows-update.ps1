# Mises à jour de Windows installées sans intervention, à la fin de l'assistant de Vasistas.
# Logiciels seulement : les pilotes ne viennent jamais de Windows Update (voir specialize.ps1).
# -Check : compte seulement les mises à jour en attente.
# Sortie : lignes « wu: … » pour l'hôte. Code 0 : à jour ; 3010 : redémarrer ; 1 : échec.
$Check = $args -contains '-Check'
$ErrorActionPreference = 'Stop'
try {
    $session = New-Object -ComObject Microsoft.Update.Session
    $found = $session.CreateUpdateSearcher().Search("IsInstalled=0 and IsHidden=0 and Type='Software'").Updates
    $todo = New-Object -ComObject Microsoft.Update.UpdateColl
    foreach ($u in $found) {
        # une mise à jour qui pose une question resterait bloquée : laissée à Windows Update
        if ($u.InstallationBehavior.CanRequestUserInput) { continue }
        if (-not $u.EulaAccepted) { $u.AcceptEula() }
        [void]$todo.Add($u)
    }
    Write-Output "wu: found $($todo.Count)"
    if ($Check -or $todo.Count -eq 0) { exit 0 }
    $downloader = $session.CreateUpdateDownloader()
    $downloader.Updates = $todo
    [void]$downloader.Download()
    $installer = $session.CreateUpdateInstaller()
    $installer.Updates = $todo
    $result = $installer.Install()
    Write-Output "wu: result $($result.ResultCode) reboot $($result.RebootRequired)"
    if ($result.RebootRequired) { exit 3010 }
    # 2 : réussi ; 3 : réussi avec des erreurs (une mise à jour sur plusieurs)
    if ($result.ResultCode -notin 2, 3) { exit 1 }
    exit 0
} catch {
    Write-Output "wu: error $($_.Exception.Message)"
    exit 1
}
