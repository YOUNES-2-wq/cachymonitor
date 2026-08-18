# Manifeste winget

Ces trois fichiers décrivent CachyMonitor pour **winget**, le gestionnaire de paquets
de Windows. Une fois le paquet accepté, l'installation tient en une ligne :

```powershell
winget install CachyMonitor
```

Les trois manifestes vivent dans `manifests/`, à l'écart de ce fichier : `winget
validate` parse **tout** ce qu'il trouve dans le dossier qu'on lui donne, et
s'étrangle sur un README écrit en Markdown.

| Fichier (dans `manifests/`) | Rôle |
|---|---|
| `YOUNES-2-wq.CachyMonitor.yaml` | racine : identifiant, version, langue par défaut |
| `YOUNES-2-wq.CachyMonitor.installer.yaml` | URL, empreinte SHA256, type d'installateur |
| `YOUNES-2-wq.CachyMonitor.locale.fr-FR.yaml` | nom, description, licence, mots-clés |

## Soumettre une version

Le dépôt officiel est [microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs).
Les manifestes y vivent dans `manifests/y/YOUNES-2-wq/CachyMonitor/<version>/`, et toute
mise à jour passe par une pull request soumise à modération.

Le plus simple est d'utiliser l'outil officiel, qui recalcule l'empreinte, met les
fichiers à jour et ouvre la pull request :

```powershell
winget install Microsoft.WingetCreate
wingetcreate update YOUNES-2-wq.CachyMonitor `
    --version 1.3.1 `
    --urls https://github.com/YOUNES-2-wq/cachymonitor/releases/download/v1.3.1/CachyMonitor-Setup-1.3.1.exe `
    --submit
```

## Vérifier avant de soumettre

```powershell
winget validate --manifest packaging\winget\manifests
```

Deux points valent d'être contrôlés à chaque version, parce qu'ils sont la cause
habituelle des rejets :

1. **L'empreinte doit correspondre au fichier publié sur GitHub**, pas à celui du
   dossier `dist\` local — il est facile de reconstruire l'exécutable après l'avoir
   téléversé, et d'obtenir deux binaires différents.
2. **`ProductCode` doit rester `{61F32A52-...}_is1`**, la clé de désinstallation
   qu'Inno Setup dérive de l'`AppId`. C'est elle qui permet à winget de reconnaître une
   installation existante et de proposer une mise à jour plutôt qu'une seconde copie.
   Ne jamais changer l'`AppId` dans `CachyMonitor.iss`.

## Automatiser

L'action [`vedantmgoyal9/winget-releaser`](https://github.com/vedantmgoyal9/winget-releaser)
soumet la pull request toute seule à chaque publication d'une release GitHub. Elle
demande un jeton d'accès personnel autorisé sur un fork de `winget-pkgs`.
