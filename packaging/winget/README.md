# Manifeste winget

Ces trois fichiers décrivent CachyMonitor pour **winget**, le gestionnaire de paquets
de Windows. Le paquet `YOUNES-2-wq.CachyMonitor` est **accepté dans le catalogue
officiel** depuis la 1.3.2
([microsoft/winget-pkgs#419610](https://github.com/microsoft/winget-pkgs/pull/419610),
fusionnée le 19/09/2026) : l'installation tient en une ligne. La mise à jour vers la
1.4.1 est soumise dans
[microsoft/winget-pkgs#445910](https://github.com/microsoft/winget-pkgs/pull/445910).

```powershell
winget install cachymonitor
```

Ces fichiers sont la copie de référence de la dernière version soumise.

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
fichiers à jour et ouvre la pull request (remplacer `<version>` par le numéro, par
exemple `1.4.2`) :

```powershell
winget install Microsoft.WingetCreate
wingetcreate update YOUNES-2-wq.CachyMonitor `
    --version <version> `
    --urls "https://github.com/YOUNES-2-wq/cachymonitor/releases/download/v<version>/CachyMonitor-Setup-<version>.exe|x64|user" `
    --out packaging\winget\manifests-generes `
    --submit
```

⚠️ **Le `|x64|user` à la fin de l'URL n'est pas décoratif.** Sans lui, l'outil refuse
de travailler : *« Plusieurs correspondances trouvées pour X86 Inno »*. Le bootstrapper
d'un installateur Inno Setup est un binaire 32 bits, même quand il installe une
application 64 bits — l'outil le détecte donc comme x86 et n'arrive plus à le rattacher
au nœud `Architecture: x64` du manifeste publié. Le suffixe impose l'architecture et la
portée à la main.

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
