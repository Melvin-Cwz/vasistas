# Vasistas Beta : l'accélération graphique

Vasistas Beta donne à Windows une vraie carte graphique, sans la lui prêter : DWM, Direct3D,
Vulkan et OpenGL s'exécutent sur la carte graphique de l'ordinateur, et l'écran composé arrive au
bureau sans passer par le processeur. C'est la piste F de
[performances-affichage.md](performances-affichage.md) (« le seul moyen de déplacer le plafond
de 28 images par seconde »), avec un autre pilote que Yttrium.

## D'où vient le pilote

Vasistas n'écrit pas ce pilote. Il utilise **accel-virt**
(https://github.com/acceleration3/accel-virt), la partie graphique de LSW, « Linux Subsystem for
Windows » (https://github.com/acceleration3/linux-subsystem-windows) :

- dans Windows, un pilote WDDM 3.2 (`avgpu.sys`) et des pilotes Direct3D 9 à 12, Vulkan, OpenGL et
  OpenCL. Windows voit « AMD Radeon 890M Graphics » comme sa carte graphique ;
- dans QEMU, une carte `virtio-gpu-av-pci` (QEMU 11.1.1 modifié) ;
- côté Linux, un moteur de rendu (`av-renderer`) qui exécute les commandes de Windows sur la carte
  graphique, avec DXVK pour Direct3D 11 et vkd3d-proton pour Direct3D 12.

Licence : le dépôt de LSW et ses paquets sont sous Apache-2.0, mais le dépôt accel-virt lui-même
n'a pas encore de fichier de licence. Vasistas Beta le compile donc sur cet ordinateur et ne le
redistribue pas. Une demande de licence à l'auteur est le préalable à toute publication.

## Ce que fait Vasistas

| Fichier | Rôle |
|---|---|
| `host/vasistas/accel.py` | trouve la compilation, choisit la carte et la mémoire partagée, construit la ligne de commande de QEMU, installe le pilote dans Windows, copie le Windows de Vasistas dans le profil Beta |
| `host/vasistas/display.py` | reçoit l'écran en dmabuf (`ScanoutDMABUF2`, `UpdateDMABUF`) |
| `host/vasistas/app.py`, `window.py` | affichent ce dmabuf tel quel ; retournement si `y0_top` vrai ; relecture pour l'aperçu |
| `host/vasistas/companion_accel.py` | la carte « Accélération graphique » de la page Affichage |
| `guest/accel/install-accel.ps1` | installe le pilote dans Windows (lancé par l'agent) |

**Depuis le 12/11/2026, Vasistas Beta est fusionné dans Vasistas** : la commande `vasistas`, ses lanceurs et ses données (`~/.local/share/vasistas`) ont la carte accélérée, sans copie du disque. Le paragraphe suivant décrit l'ancien profil à part, encore lisible avec `VASISTAS_PROFILE=beta`.

Le profil Beta (`VASISTAS_PROFILE=beta`, commande `~/.local/bin/vasistas-beta`, lanceur
« Vasistas Beta ») a ses propres données dans `~/.local/share/vasistas-beta` : une copie du
disque de Windows, faite au premier démarrage. La VM principale n'est jamais modifiée. Les deux
ne tournent jamais en même temps.

### Premier démarrage

1. Vasistas copie le disque, les variables UEFI et les réglages de Vasistas.
2. Windows démarre avec deux cartes : `virtio-vga` (l'affichage habituel) et la carte accélérée,
   encore sans pilote. Le paquet de pilotes est sur le CD de partage.
3. « Installer le pilote dans Windows » (ou `vasistas-beta accel install`) crée le point de
   restauration `avant-accel`, puis l'agent lance `install-accel.ps1` : copie dans `C:\av`,
   recherche de pilotes sur Windows Update coupée (Windows Update reste actif, contrairement à
   l'étape « prepare » d'accel-virt), `provision.ps1 sign`, `install -NoVerifier`, `check`.
4. Windows redémarre sur la carte accélérée seule (`-vga none`, `-display dbus,gl=on`).

Depuis le 12/11/2026, le pilote est imposé dès l'installation de Windows : `specialize.ps1` coupe
la recherche de pilotes sur Windows Update avant le premier démarrage (sans quoi Windows posait le
vrai pilote AMD ou NVIDIA sur la carte, en erreur 43, et `pnputil` refusait ensuite le nôtre avec
le code 259), `install-accel.ps1` retire un tel pilote s'il est déjà là, et l'assistant installe
le pilote à son étape « Pilotes graphiques », en citant son auteur, acceleration3.

### Réglages et choix automatiques

- **Carte** : automatique = la carte intégrée sur batterie et en équilibré, la carte dédiée en
  Performance si elle est allumée. La liste des cartes est gardée en cache (`gpus.json`) tant que
  le matériel ne change pas : `vulkaninfo` réveillerait la carte dédiée à chaque démarrage.
- **Mémoire partagée** (`hostmem`) : 2, 4 ou 8 Go selon le profil de puissance. Sur une carte
  intégrée, c'est de la RAM.
- **Affichage** : QEMU exporte l'écran sur le nœud de rendu de la carte intégrée (`rendernode=`),
  celle qui affiche le bureau ; GTK l'importe sans changer de carte.
- **Caches de shaders** de DXVK, vkd3d-proton, Mesa et NVIDIA dans le profil : la deuxième
  ouverture d'une application ne recompile rien.
- **Moteur de rendu isolé**, toujours : un plantage du pilote Linux ne coûte à Windows qu'une
  réinitialisation de la carte. Dans QEMU même, l'exécuteur prend le contexte EGL de l'affichage
  `dbus,gl=on` et QEMU s'arrête (assertion d'epoxy).
- **Résolution** : le pilote ignore `SetUIInfo` ; Vasistas change la liste de modes du dispositif
  par QMP (`qom-set … modes`), et Windows passe au seul mode offert.

## Mesures (2026-11-01, Radeon 890M, 4 cœurs, Bloc-notes ouvert)

| | Vasistas 0.10 (WARP) | Vasistas Beta |
|---|---|---|
| Compositions de DWM par seconde | 28 | 60 |
| Latence de frappe, médiane | 41 ms | 37 ms (p90 67 ms) |
| QEMU au repos | 17 % d'un cœur | 16 % au plancher, pics à 40-80 % pendant les tâches de fond de Windows juste après le démarrage |
| Moteur de rendu au repos | – | 0 % |
| Images reçues par l'hôte au repos | – | 0 |

Juste après l'installation du pilote, Windows travaille quelques minutes (Windows Update,
Microsoft Store) : la première mesure donnait 102 ms de latence médiane. Mesurer après quelques
minutes.

## Compiler accel-virt

Dans `~/.local/opt/accel-virt` (clone du dépôt, commit a9c01985) :

```
tools/fetch_windows_kit.sh && python3 tools/fetch_khronos_registries.py && tools/fetch_qemu.sh
git submodule update --init --recursive third_party/dxvk third_party/vkd3d-proton
cmake -S . -B build -G Ninja -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_C_COMPILER=clang
cmake --build build --target drivers && cmake --install build --prefix $PWD/build/av-drivers
cmake -S . -B build-qemu -G Ninja -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_C_COMPILER=clang \
      -DCMAKE_BUILD_TYPE=Release -DAV_QEMU=ON -DAV_OPENCL_LIBRARY=/usr/lib/x86_64-linux-gnu/libOpenCL.so.1
cmake --build build-qemu --target qemu av_executor av-renderer
PATH=$PWD/hostbin:$PATH tools/build_d3d_runtime.sh
```

Pièges rencontrés sur elementary OS 9 :

- paquets : `clang lld llvm cmake glslang-tools libsdl3-dev libslirp-dev libpipewire-0.3-dev
  libglib2.0-dev libpixman-1-dev libgtk-3-dev libgbm-dev libdrm-dev libegl-dev libepoxy-dev
  libvulkan-dev libcap-ng-dev flex bison` ;
- sans `libOpenCL.so` (paquet de développement), CMake ne trouve pas OpenCL et l'exécuteur ne se
  charge plus (`undefined symbol: clGetProgramInfo`) : d'où `-DAV_OPENCL_LIBRARY` ;
- vkd3d-proton veut `widl` : celui de `mingw-w64-tools`, extrait sans installation dans
  `hostbin/` (`apt-get download` puis `dpkg-deb -x`), comme `vulkaninfo` (`vulkan-tools`) ;
- la cible `av_echo_executor` (un double de test) ne compile pas à ce commit : ne construire que
  `qemu av_executor av-renderer`.

## Limites connues

- Bêta d'un pilote alpha : Windows en mode signature de test, écran bleu possible. Revenir en
  arrière : « Retirer le pilote », ou le point de restauration `avant-accel`, ou supprimer
  `~/.local/share/vasistas-beta` (la VM principale n'est pas touchée).
- Une seule résolution à la fois, 4095 pixels de côté au plus : l'écran large de la piste A
  (6320 pixels) ne passe pas.
- Fréquence fixe de 60 Hz, sans accord de phase avec l'écran de l'hôte.
