#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
NPOAP - Script de verification d'installation
Verifie toutes les dependances et modules requis pour NPOAP
"""

import sys
import os
import importlib.metadata as _importlib_metadata
from pathlib import Path


def _patch_distributions_skip_null_metadata():
    """
    Contourne un bug CuPy / importlib.metadata : certaines entrees de site-packages
    ont distribution.metadata is None, ce qui fait echouer cupy._detect_duplicate_installation
    puis tout import transitif (dask -> specutils).
    """
    _orig = _importlib_metadata.distributions

    def _filtered():
        for dist in _orig():
            if getattr(dist, "metadata", None) is not None:
                yield dist

    _importlib_metadata.distributions = _filtered  # type: ignore[assignment]


_patch_distributions_skip_null_metadata()


def _configure_stdio_encoding():
    """
    Compatible console Windows + redirection vers .log puis `type`.
    Forcer UTF-8 provoque des caracteres bizarres sous cmd CP850/1252.
    """
    if sys.platform == "win32":
        enc = "cp1252"
    else:
        enc = "utf-8"
    for stream in (getattr(sys, "stdout", None), getattr(sys, "stderr", None)):
        if stream is None:
            continue
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding=enc, errors="replace")
            except (OSError, ValueError, TypeError, AttributeError):
                pass


_configure_stdio_encoding()

# Symboles ASCII uniquement (lisibles sous cmd Windows apres redirection / type)
_OK = "[OK]"
_ERR = "[X]"
_WARN = "[!]"
_INFO = "[i]"

# Codes de couleur ANSI pour le terminal (vides si sortie non interactive / redirigee)
class Colors:
    _use = hasattr(sys.stdout, "isatty") and sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
    GREEN = '\033[92m' if _use else ''
    YELLOW = '\033[93m' if _use else ''
    RED = '\033[91m' if _use else ''
    BLUE = '\033[94m' if _use else ''
    CYAN = '\033[96m' if _use else ''
    BOLD = '\033[1m' if _use else ''
    RESET = '\033[0m' if _use else ''
    UNDERLINE = '\033[4m' if _use else ''

def _print_safe(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "cp1252"
        print(msg.encode(enc, errors="replace").decode(enc, errors="replace"))


def print_header(text):
    """Affiche un en-tete formate"""
    _print_safe(f"\n{Colors.BOLD}{Colors.BLUE}{'='*70}{Colors.RESET}")
    _print_safe(f"{Colors.BOLD}{Colors.BLUE}{text:^70}{Colors.RESET}")
    _print_safe(f"{Colors.BOLD}{Colors.BLUE}{'='*70}{Colors.RESET}\n")

def print_success(text):
    """Affiche un message de succes"""
    _print_safe(f"{Colors.GREEN}{_OK}{Colors.RESET} {text}")

def print_error(text):
    """Affiche un message d'erreur"""
    _print_safe(f"{Colors.RED}{_ERR}{Colors.RESET} {text}")

def print_warning(text):
    """Affiche un message d'avertissement"""
    _print_safe(f"{Colors.YELLOW}{_WARN}{Colors.RESET} {text}")

def print_info(text):
    """Affiche un message d'information"""
    _print_safe(f"{Colors.CYAN}{_INFO}{Colors.RESET} {text}")

def check_module(module_name, required=True, version_attr='__version__', optional_reason=""):
    """
    Verifie si un module est disponible
    
    Parameters:
    -----------
    module_name : str
        Nom du module a verifier
    required : bool
        Si True, module est requis (erreur si absent). Si False, optionnel (avertissement si absent)
    version_attr : str
        Attribut contenant la version (par defaut '__version__')
    optional_reason : str
        Raison pour laquelle le module est optionnel (si required=False)
    
    Returns:
    --------
    tuple : (bool, str, str)
        (disponible, version, message)
    """
    try:
        module = __import__(module_name)
        version = getattr(module, version_attr, "version inconnue")
        return True, version, f"{module_name} {version}"
    except ImportError as e:
        if required:
            return False, None, f"{module_name} non installe (REQUIS)"
        else:
            reason = f" ({optional_reason})" if optional_reason else ""
            return False, None, f"{module_name} non installe{reason} (optionnel)"
    except Exception as e:
        hint = ""
        msg = str(e)
        if "'NoneType' object has no attribute 'get'" in msg or "_detect_duplicate_installation" in msg:
            hint = (
                " - indice: CuPy ou metadonnees pip incoherentes (pip check ; "
                "pip uninstall cupy cupy-cuda11x cupy-cuda12x ... puis une seule variante si GPU requis)."
            )
        if required:
            return False, None, f"{module_name} import echoue (REQUIS): {type(e).__name__}: {e}{hint}"
        reason = f" ({optional_reason})" if optional_reason else ""
        return False, None, f"{module_name} import echoue{reason} (optionnel): {type(e).__name__}: {e}{hint}"

def check_prospector():
    """Verifie l'installation complete de Prospector"""
    results = {
        'available': False,
        'version': None,
        'components': {},
        'errors': [],
        'warnings': []
    }
    
    # Test 1: prospect module (ImportError ou erreur si SPS_HOME / FSPS incomplet)
    try:
        import prospect
        results['available'] = True
        results['version'] = getattr(prospect, '__version__', 'version inconnue')
        results['components']['prospect'] = True
    except ImportError as e:
        results['components']['prospect'] = False
        results['errors'].append(f"prospect non disponible: {e}")
        return results
    except Exception as e:
        results['available'] = False
        results['components']['prospect'] = False
        results['errors'].append(
            f"prospect installe mais import echoue (souvent SPS_HOME ou FSPS manquant): {e}"
        )
        results['warnings'].append(
            "Definir SPS_HOME et donnees FSPS, ou reinstaller via Installation_fsps/prospector.bat (WSL)"
        )
        return results
    
    # Test 2: sedpy.observate
    try:
        from sedpy import observate
        results['components']['sedpy.observate'] = True
    except ImportError as e:
        results['components']['sedpy.observate'] = False
        results['errors'].append(f"sedpy.observate non disponible: {e}")
        results['warnings'].append("sedpy doit etre installe depuis GitHub, pas PyPI")
    
    # Test 3: SpecModel
    try:
        from prospect.models import SpecModel
        results['components']['SpecModel'] = True
    except ImportError:
        try:
            from prospect.models import SedModel
            results['components']['SedModel'] = True
            results['warnings'].append("SedModel disponible (version ancienne), utilisez SpecModel dans les versions recentes")
        except ImportError as e:
            results['components']['SpecModel'] = False
            results['components']['SedModel'] = False
            results['warnings'].append(f"SpecModel/SedModel non disponible: {e}")
    
    # Test 4: FastStepBasis
    try:
        from prospect.sources import FastStepBasis
        results['components']['FastStepBasis'] = True
    except ImportError as e:
        results['components']['FastStepBasis'] = False
        results['warnings'].append(f"FastStepBasis non disponible: {e} (FSPS peut etre requis)")
    
    # Test 5: fit_model
    try:
        from prospect.fitting import fit_model
        results['components']['fit_model'] = True
    except ImportError as e:
        results['components']['fit_model'] = False
        results['warnings'].append(f"fit_model non disponible: {e}")
    
    # Test 6: FSPS (optionnel)
    try:
        import fsps
        results['components']['FSPS'] = True
        results['fsps_version'] = getattr(fsps, '__version__', 'version inconnue')
    except ImportError:
        results['components']['FSPS'] = False
        results['warnings'].append("FSPS non installe (Prospector utilisera des fichiers stub)")
    
    # Test 7: SPS_HOME
    sps_home = os.environ.get('SPS_HOME')
    if sps_home:
        results['SPS_HOME'] = sps_home
        # Verifier que le fichier stub existe
        stub_file = Path(sps_home) / 'dust' / 'Nenkova08_y010_torusg_n10_q2.0.dat'
        if stub_file.exists():
            results['components']['FSPS_stub'] = True
            # Verifier le format du fichier stub
            try:
                with open(stub_file, 'r') as f:
                    lines = f.readlines()
                if len(lines) >= 129:
                    # Verifier le separateur (3 espaces)
                    if len(lines) >= 5:
                        data_line = lines[4].strip()
                        if data_line and not data_line.startswith('#'):
                            cols = data_line.split('   ')  # 3 espaces
                            if len(cols) == 10:
                                results['components']['FSPS_stub_format'] = True
                            else:
                                results['warnings'].append("Fichier stub FSPS: format incorrect (nombre de colonnes ou separateur)")
                                results['components']['FSPS_stub_format'] = False
                else:
                    results['warnings'].append(f"Fichier stub FSPS: nombre de lignes insuffisant ({len(lines)} < 129)")
                    results['components']['FSPS_stub_format'] = False
            except Exception as e:
                results['warnings'].append(f"Erreur lors de la verification du fichier stub: {e}")
                results['components']['FSPS_stub_format'] = False
        else:
            results['components']['FSPS_stub'] = False
            results['warnings'].append(f"Fichier stub FSPS manquant: {stub_file}")
    else:
        results['SPS_HOME'] = None
        results['warnings'].append("SPS_HOME non defini (sera cree automatiquement si necessaire)")
    
    return results

def check_local_modules():
    """Verifie que les modules locaux de NPOAP sont disponibles"""
    results = {
        'core': False,
        'gui': False,
        'utils': False,
        'config': False,
        'errors': []
    }
    
    # Verifier que nous sommes dans le repertoire NPOAP
    npoap_dir = Path(__file__).parent
    
    # Test 1: core
    try:
        import core
        results['core'] = True
    except ImportError as e:
        results['errors'].append(f"Module 'core' non disponible: {e}")
        if not (npoap_dir / 'core').exists():
            results['errors'].append(f"Repertoire 'core' introuvable dans {npoap_dir}")
    
    # Test 2: gui
    try:
        import gui
        results['gui'] = True
    except ImportError as e:
        results['errors'].append(f"Module 'gui' non disponible: {e}")
        if not (npoap_dir / 'gui').exists():
            results['errors'].append(f"Repertoire 'gui' introuvable dans {npoap_dir}")
    
    # Test 3: utils
    try:
        import utils
        results['utils'] = True
    except ImportError as e:
        results['errors'].append(f"Module 'utils' non disponible: {e}")
        if not (npoap_dir / 'utils').exists():
            results['errors'].append(f"Repertoire 'utils' introuvable dans {npoap_dir}")
    
    # Test 4: config.py
    config_file = npoap_dir / 'config.py'
    if config_file.exists():
        results['config'] = True
    else:
        results['errors'].append(f"Fichier 'config.py' introuvable dans {npoap_dir}")
    
    # Test 5: main.py
    main_file = npoap_dir / 'main.py'
    if not main_file.exists():
        results['errors'].append(f"Fichier 'main.py' introuvable dans {npoap_dir}")
    
    return results

def main():
    """Fonction principale de verification"""
    _configure_stdio_encoding()

    # En-tete
    print_header("VERIFICATION DE L'INSTALLATION NPOAP")
    
    # Compteurs
    required_ok = 0
    required_total = 0
    optional_ok = 0
    optional_total = 0
    errors = []
    warnings = []
    
    # === VERIFICATION DES DEPENDANCES CORE (REQUISES) ===
    print_header("1. Dependances Core (Requis)")
    
    core_modules = [
        ('numpy', True),
        ('scipy', True),
        ('pandas', True),
        ('astropy', True),
        ('photutils', True),
        ('ccdproc', True),
        ('astroquery', True),
        ('matplotlib', True),
        ('requests', True),
        # Paquet PyPI "Pillow", module Python "PIL" - ne pas ajouter de 3e element (sinon import "Pillow" echoue)
        ('PIL', True),
        ('emcee', True),
        ('specutils', True),
        ('statsmodels', True),
        ('pylightcurve', True),
    ]
    
    for module_info in core_modules:
        if len(module_info) == 2:
            module_name, required = module_info
            import_name = module_name
        else:
            module_name, required, import_name = module_info
        
        available, version, message = check_module(import_name, required=required)
        
        if required:
            required_total += 1
            if available:
                print_success(message)
                required_ok += 1
            else:
                print_error(message)
                errors.append(message)
        else:
            optional_total += 1
            if available:
                print_success(f"{message} (optionnel)")
                optional_ok += 1
            else:
                print_warning(message)
                warnings.append(message)
    
    # === VERIFICATION DES DEPENDANCES OPTIONNELLES ===
    print_header("2. Dependances Optionnelles")
    
    optional_modules = [
        ('phoebe', False, "Etoiles binaires (PHOEBE2)"),
        ('rebound', False, "Simulation N-body"),
        ('ultranest', False, "Nested sampling bayesien"),
        ('stdpipe', False, "STDPipe (photometrie transitoires)"),
    ]
    missing_physics_bundle = False
    for module_info in optional_modules:
        if len(module_info) == 2:
            module_name, optional_reason = module_info
            import_name = module_name
        else:
            module_name, _, optional_reason = module_info
            import_name = module_name
        
        available, version, message = check_module(import_name, required=False, optional_reason=optional_reason)
        optional_total += 1
        if available:
            print_success(f"{message} (optionnel)")
            optional_ok += 1
        else:
            print_warning(message)
            warnings.append(message)
            missing_physics_bundle = True
    if missing_physics_bundle:
        print_info(
            "Indice : PHOEBE, rebound, ultranest et stdpipe sont listes dans requirements_install_optionnels.txt - "
            "pip install -r requirements_install_optionnels.txt (astroenv) ou install_optionnels.bat."
        )
    
    # CuPy (GPU) - verification speciale
    print_info("Verification de CuPy (acceleration GPU)...")
    try:
        import cupy as cp
        gpu_available = cp.cuda.is_available()
        if gpu_available:
            device = cp.cuda.Device(0)
            compute_capability = device.compute_capability
            print_success(f"CuPy {cp.__version__} installe - GPU disponible (Compute Capability: {compute_capability})")
            optional_ok += 1
        else:
            print_warning(f"CuPy {cp.__version__} installe - GPU non disponible (CUDA requis)")
            warnings.append("CuPy installe mais GPU non disponible")
        optional_total += 1
    except Exception as e:
        if isinstance(e, ImportError):
            print_warning("CuPy non installe (optionnel - acceleration GPU)")
            warnings.append("CuPy non installe (optionnel)")
        else:
            msg = str(e)
            hint = ""
            if "'NoneType' object has no attribute 'get'" in msg or "_detect_duplicate_installation" in msg:
                hint = (
                    " - indice: metadonnees pip / plusieurs variantes CuPy ; "
                    "voir docs/MANUEL_INSTALLATION.md (Depannage CuPy)."
                )
            print_warning(f"CuPy import ou GPU : {type(e).__name__}: {e}{hint}")
            warnings.append(f"CuPy: {e}")
        optional_total += 1
    
    # === VERIFICATION DE PROSPECTOR ===
    print_header("3. Prospector (Optionnel - Analyse Spectroscopique)")
    
    prospector_results = check_prospector()
    
    if prospector_results['available']:
        print_success(f"prospect {prospector_results['version']} disponible")
        optional_ok += 1
        
        # Afficher les composants
        print(f"  {Colors.CYAN}Composants Prospector:{Colors.RESET}")
        for component, available in prospector_results['components'].items():
            if available:
                _print_safe(f"    {Colors.GREEN}{_OK}{Colors.RESET} {component}")
            else:
                _print_safe(f"    {Colors.YELLOW}{_WARN}{Colors.RESET} {component} non disponible")
        
        # Afficher SPS_HOME
        if prospector_results['SPS_HOME']:
            print(f"  {Colors.CYAN}SPS_HOME:{Colors.RESET} {prospector_results['SPS_HOME']}")
        else:
            print_warning("  SPS_HOME non defini")
        
        # Afficher FSPS si installe
        if prospector_results['components'].get('FSPS'):
            print_success(f"  FSPS {prospector_results.get('fsps_version', 'version inconnue')} installe")
        else:
            print_warning("  FSPS non installe (utilisation de fichiers stub)")
    else:
        print_warning("Prospector indisponible ou incomplet (optionnel)")
        if prospector_results['errors']:
            for error in prospector_results['errors']:
                print_warning(f"  {error}")
                warnings.append(f"Prospector: {error}")
    
    optional_total += 1
    
    # Ajouter les avertissements de Prospector
    warnings.extend([f"Prospector: {w}" for w in prospector_results.get('warnings', [])])
    
    # === VERIFICATION DES MODULES LOCAUX ===
    print_header("4. Modules Locaux NPOAP")
    
    local_results = check_local_modules()
    
    if local_results['core']:
        print_success("Module 'core' disponible")
    else:
        print_error("Module 'core' non disponible")
        errors.extend([f"Modules locaux: {e}" for e in local_results['errors'] if 'core' in e.lower()])
    
    if local_results['gui']:
        print_success("Module 'gui' disponible")
    else:
        print_error("Module 'gui' non disponible")
        errors.extend([f"Modules locaux: {e}" for e in local_results['errors'] if 'gui' in e.lower()])
    
    if local_results['utils']:
        print_success("Module 'utils' disponible")
    else:
        print_error("Module 'utils' non disponible")
        errors.extend([f"Modules locaux: {e}" for e in local_results['errors'] if 'utils' in e.lower()])
    
    if local_results['config']:
        print_success("Fichier 'config.py' trouve")
    else:
        print_error("Fichier 'config.py' introuvable")
        errors.extend([f"Modules locaux: {e}" for e in local_results['errors'] if 'config' in e.lower()])
    
    # === VERIFICATION DE L'ENVIRONNEMENT PYTHON ===
    print_header("5. Environnement Python")
    
    print_info(f"Version Python: {sys.version}")
    print_info(f"Executable Python: {sys.executable}")
    print_info(f"Plateforme: {sys.platform}")
    
    # Verifier si nous sommes dans un environnement virtuel ou Conda
    _conda = bool(os.environ.get("CONDA_DEFAULT_ENV") or os.environ.get("CONDA_PREFIX"))
    _venv = hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    )
    if _conda or _venv:
        if _conda and os.environ.get("CONDA_DEFAULT_ENV"):
            print_success(f"Conda detecte (env: {os.environ.get('CONDA_DEFAULT_ENV')})")
        else:
            print_success("Environnement virtuel/Conda detecte")
    else:
        print_warning("Aucun environnement virtuel/Conda detecte (utilisation de Python systeme)")
    
    # === RESUME FINAL ===
    print_header("RESUME")
    
    print(f"{Colors.BOLD}Dependances Requises:{Colors.RESET}")
    print(f"  {Colors.GREEN if required_ok == required_total else Colors.RED}"
          f"{required_ok}/{required_total} installees{Colors.RESET}")
    
    print(f"\n{Colors.BOLD}Dependances Optionnelles:{Colors.RESET}")
    print(f"  {Colors.CYAN}{optional_ok}/{optional_total} installees{Colors.RESET}")
    
    # Afficher les erreurs
    if errors:
        print(f"\n{Colors.BOLD}{Colors.RED}Erreurs ({len(errors)}):{Colors.RESET}")
        for i, error in enumerate(errors, 1):
            print(f"  {i}. {Colors.RED}{error}{Colors.RESET}")
    
    # Afficher les avertissements
    if warnings:
        print(f"\n{Colors.BOLD}{Colors.YELLOW}Avertissements ({len(warnings)}):{Colors.RESET}")
        for i, warning in enumerate(warnings, 1):
            print(f"  {i}. {Colors.YELLOW}{warning}{Colors.RESET}")
    
    # Conclusion
    print()
    if required_ok == required_total and not local_results['errors']:
        print(f"{Colors.BOLD}{Colors.GREEN}{'='*70}{Colors.RESET}")
        _print_safe(f"{Colors.BOLD}{Colors.GREEN}{_OK} Installation NPOAP verifiee avec succes!{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.GREEN}{'='*70}{Colors.RESET}")
        if warnings:
            print(f"\n{Colors.YELLOW}Note: Certaines fonctionnalites optionnelles ne sont pas disponibles,{Colors.RESET}")
            print(f"{Colors.YELLOW}mais les fonctionnalites de base de NPOAP fonctionneront correctement.{Colors.RESET}")
        return 0
    else:
        print(f"{Colors.BOLD}{Colors.RED}{'='*70}{Colors.RESET}")
        _print_safe(f"{Colors.BOLD}{Colors.RED}{_ERR} Installation incomplete - Veuillez corriger les erreurs ci-dessus{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.RED}{'='*70}{Colors.RESET}")
        if errors:
            print(f"\n{Colors.YELLOW}Pour installer les dependances manquantes:{Colors.RESET}")
            print(f"  conda activate astroenv")
            print(f"  pip install -r requirements.txt")
        return 1

if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print(f"\n\n{Colors.YELLOW}Verification interrompue par l'utilisateur{Colors.RESET}")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n{Colors.RED}Erreur inattendue lors de la verification: {e}{Colors.RESET}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
