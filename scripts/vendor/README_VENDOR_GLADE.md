# Fichiers vendus (catalogue GLADE+)

- **`convert_glade_catalog.py`**  
  Basé sur `ConvertGalaxyCatalog.py` (écosystème GLADE+ / outils historiques de conversion).  
  Mise à jour : retélécharger depuis le même chemin relatif dans le dépôt d’origine si le format GLADE+ change.

NPOAP l’utilise pour générer `Gladeplus.h5` (PyTables) ; en usage courant, placez le fichier fourni dans `~/.npoap/catalogues/`.  
L’application lit le HDF5 via **h5py** (`core/glade_alert_targets.py`) ; **PyTables** n’est requis que pour la conversion : `pip install -r requirements_glade_build.txt`.
