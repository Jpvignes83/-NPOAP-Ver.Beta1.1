
import os
import glob
from collections import defaultdict
import tkinter.font as tkfont
import numpy as np
import shutil
import exoclock
import warnings
import matplotlib
import webbrowser
import concurrent.futures
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
import hops.pylightcurve41 as plc
from astropy.coordinates import SkyCoord
from astropy.wcs import WCS
from photutils.aperture import CircularAperture, aperture_photometry

from matplotlib.cm import Greys, Greys_r


from hops.application_windows import MainWindow, AddOnWindow
from hops.hops_tools.fits import get_fits_data_and_header
from hops.hops_tools.image_analysis import image_find_stars, image_plate_solve, cartesian_to_polar
from hops.hops_tools.trans_coeff_npoap import delta_mag_from_flux_ratio, effective_transformation_slope

def _log_param_bool_safe(log, key, default=False):
    try:
        v = log.get_param(key)
    except Exception:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("true", "yes", "1", "on"):
        return True
    if s in ("false", "no", "0", "off", ""):
        return False
    return default


class PhotometryWindow(MainWindow):

    def __init__(self, log):

        MainWindow.__init__(self, log, name='HOPS - Photometry', position=2)

        ##############################################################################
        # set up advanced settings window

        self.advanced_settings_window = AddOnWindow(self, name='Advanced settings', position=2)
        self.show_advanced_settings_button = self.Button(text='Advanced settings', command=self.advanced_settings_window.show)

        self.use_variable_aperture = self.advanced_settings_window.CheckButton(
            text='Vary the aperture size proportionally to the variations of the PSF size.',
            initial=self.log.get_param('use_variable_aperture'),
            command=self.update_window
        )

        self.use_geometric_center = self.advanced_settings_window.CheckButton(
            text='Align the aperture with the geometric center instead of the PSF peak.',
            initial=self.log.get_param('use_geometric_center'),
            command=self.update_window
        )

        self.sky_inner_aperture = self.advanced_settings_window.Entry(
            value=self.log.get_param('sky_inner_aperture'),
            instance=float,
            command=self.update_window
        )

        self.sky_outer_aperture = self.advanced_settings_window.Entry(
            value=self.log.get_param('sky_outer_aperture'),
            instance=float,
            command=self.update_window
        )

        self.saturation = self.advanced_settings_window.Entry(
            value=self.log.get_param('saturation'),
            instance=float,
            command=self.update_window
        )

        self.star_size_arcsec = self.advanced_settings_window.Entry(
            value=self.log.get_param('star_size_arcsec'),
            instance=float,
            command=self.update_window
        )

        self.camera_gain = self.advanced_settings_window.Entry(
            value=self.log.get_param('camera_gain'),
            instance=float,
            command=self.update_window
        )

        self.advanced_settings_window.setup_window([
            [],
            [
                [self.advanced_settings_window.Label(text='Inner sky-ring radius, relatively to the aperture'), 0],
                [self.sky_inner_aperture, 1],
                [self.advanced_settings_window.Label(text='(default = 1.7)'), 2]
             ],
            [
                [self.advanced_settings_window.Label(text='Outer sky-ring radius, relatively to the aperture'), 0],
                [self.sky_outer_aperture, 1],
                [self.advanced_settings_window.Label(text='(default = 2.4)'), 2]
            ],
            [[self.advanced_settings_window.Label(text='Note: the bright pixels inside the sky-ring\nare NOT taken into account for the sky background estimation.'), 0, 3]],
            [],
            [
                [self.advanced_settings_window.Label(text='Saturation limit, relatively to the full-well depth'), 0],
                [self.saturation, 1],
                [self.advanced_settings_window.Label(text='(default = 0.95)'), 2]],
            [],
            [
                [self.advanced_settings_window.Label(text='Star FWHM in arcseconds (approximate)'), 0],
                [self.star_size_arcsec, 1],
                [self.advanced_settings_window.Label(text='(default = 4.0)'), 2]],
            [],
            [
                [self.advanced_settings_window.Label(text='Camera gain in e/ADU'), 0],
                [self.camera_gain, 1],
                [self.advanced_settings_window.Label(text='(default = 1.0)'), 2]],
            [],
            [[self.use_variable_aperture, 0, 3]],
            [[self.use_geometric_center, 0, 3]],
            [],
        ])
        ##############################################################################

        ##############################################################################
        # set up variables

        self.bin_fits = self.log.get_param('bin_fits')
        self.burn_limit = self.log.get_param('burn_limit')
        self.max_targets = self.log.get_param('max_comparisons') + 1
        self.target_ra_dec = self.log.get_param('target_ra_dec')
        self.visible_fov_x_min = self.log.get_param('min_x')
        self.visible_fov_y_min = self.log.get_param('min_y')
        self.visible_fov_x_max = self.log.get_param('max_x')
        self.visible_fov_y_max = self.log.get_param('max_y')
        self.centroids_snr = self.log.get_param('centroids_snr')
        self.stars_snr = self.log.get_param('stars_snr')

        self.all_frames = plc.open_dict(self.log.all_frames)
        self.science_files = []
        self.exposure_time = []

        for science_file in self.all_frames:
            if not self.all_frames[science_file][self.log.skip_key]:
                self.science_files.append([self.all_frames[science_file][self.log.time_key], science_file])
                self.exposure_time.append(self.all_frames[science_file][self.log.get_param('exposure_time_key')])

        self.science_files.sort()
        self.science_files = [ff[1] for ff in self.science_files]
        self.exposure_time = np.median(self.exposure_time)

        self.all_stars = plc.open_dict(self.log.all_stars)
        self.in_fov = self.all_stars['in_fov']
        self.all_stars = self.all_stars['all_stars']

        self.science_file = self.science_files[0]
        self.fits_data, self.fits_header = get_fits_data_and_header(
            os.path.join(self.log.reduction_directory, self.science_file))

        self.show_good_comparisons = self.CheckButton(text='Show stars with flux similar\nto the target (+/- %):',
                                                      initial=self.log.get_param('show_good_comparisons'),
                                                      command=self.update_window)
        self.show_good_comparisons_percent = self.DropDown(initial=self.log.get_param('show_good_comparisons_percent'),
                                                           options=[10, 20, 30, 40, 50], instance=float,
                                                           command=self.update_window, width=8)
        self.plate_solution = None
        self._variable_blink_scheduled = False
        self._variable_blink_phase = 0
        self._t1_auto_comp_sig = None
        self._plate_solve_annots = []
        self._resize_after_id = None
        self._fwhm_ap_scale = 1.5  # rayon d'ouverture ≈ FWHM × ce facteur (plancher PSF × 3)
        self._auto_comp_refresh_scheduled = False
        ##############################################################################

        ##############################################################################
        # set up plot

        self.fits_figure = self.FitsWindow(fits_data=self.fits_data, fits_header=self.fits_header, input_name=self.science_file,
                                           input_options=self.log.get_param('photometry_fov_options'),
                                           max_figsize_percent=(0.98, 0.95),
                                           show_controls=True, show_axes=True,
                                           subplots_adjust=(0.07, 0.99, 0.05, 0.85))

        self.fits_figure.canvas.callbacks.connect('button_press_event', self.select_star)

        self.fits_figure.ax.add_patch(mpatches.Rectangle((self.visible_fov_x_min + 1, self.visible_fov_y_min + 1),
                                                         self.visible_fov_x_max - self.visible_fov_x_min - 2,
                                                         self.visible_fov_y_max - self.visible_fov_y_min - 2,
                                                         ec='r', fill=False, label='Available FOV'))
        ##############################################################################

        ##############################################################################
        # set up targets

        self.targets_indication = self.IntVar(0)

        self.targets = [
            [
                self.Radiobutton(text='      Target           ', variable=self.targets_indication, value=0),
                self.Entry(value=self.log.get_param('target_aperture'), instance=float, command=self.update_window),
                self.Label(text=self.log.get_param('target_x_position'), instance=float),
                self.Label(text=self.log.get_param('target_y_position'), instance=float),
                mpatches.Circle((-1000, -1000), 1, ec='r', fill=False),
                mpatches.Circle((-1000, -1000), 1, ec='r', fill=False),
                mpatches.Circle((-1000, -1000), 1, ec='r', fill=False),
                self.fits_figure.ax.text(-1000, -1000, 'T', color='r', fontsize=15, va='top'),
                self.Label(text=''),
                self.Label(text='-', instance=str),
                self.Label(text=0.0, instance=float),
                self.Label(text=0.0, instance=float),
                self.Label(text=0.0, instance=float),
                self.Label(),
                self.Label(text='-', instance=str),
                False,
                0, 0,
                self.Label(text='-', instance=str),
            ]
        ]

        for comparison in range(self.log.get_param('max_comparisons')):

            self.targets.append(
                [
                    self.Radiobutton(text='Comparison {0}     '.format(comparison + 1), variable=self.targets_indication, value=comparison + 1),
                    self.Entry(value=self.log.get_param('comparison_{0}_aperture'.format(comparison + 1)), instance=float, command=self.update_window),
                    self.Label(text=self.log.get_param('comparison_{0}_x_position'.format(comparison + 1)), instance=float),
                    self.Label(text=self.log.get_param('comparison_{0}_y_position'.format(comparison + 1)), instance=float),
                    mpatches.Circle((-1000, -1000), 1, ec='#07fefc', fill=False),
                    mpatches.Circle((-1000, -1000), 1, ec='#07fefc', fill=False),
                    mpatches.Circle((-1000, -1000), 1, ec='#07fefc', fill=False),
                    self.fits_figure.ax.text(-1000, -1000, 'C{0}'.format(comparison + 1), color='#07fefc', fontsize=15, va='top'),
                    self.Button(text='CLEAR', command=self.clear_target(comparison + 1)),
                    self.Label(text='-', instance=str),
                    self.Label(text=0.0, instance=float),
                    self.Label(text=0.0, instance=float),
                    self.Label(text=0.0, instance=float),
                    self.Label(),
                    self.Label(text='-', instance=str),
                    False,
                    0, 0,
                    self.Label(text='-', instance=str),
                ]
            )

        for target in self.targets:
            self.fits_figure.ax.add_patch(target[4])
            self.fits_figure.ax.add_patch(target[5])
            self.fits_figure.ax.add_patch(target[6])

        ##############################################################################

        ##############################################################################
        # set up good comparisons

        self.good_comps_boxes = []
        for comparison in range(100):
            if comparison == 0:
                good_comps_box = mpatches.Rectangle((-1000, -1000),
                                             10 * self.fits_header[self.log.psf_key],
                                             10 * self.fits_header[self.log.psf_key],
                                             ec='y', fill=False,
                                             label='Stars of similar flux to the target')
            else:
                good_comps_box = mpatches.Rectangle((-1000, -1000),
                                             10 * self.fits_header[self.log.psf_key],
                                             10 * self.fits_header[self.log.psf_key],
                                             ec='y', fill=False)

            self.good_comps_boxes.append(good_comps_box)

        for good_comps_box in self.good_comps_boxes:
            self.fits_figure.ax.add_patch(good_comps_box)

        self.fits_figure.ax.legend(loc=(0, 1.01))
        ##############################################################################

        ##############################################################################
        # other widgets

        photometry_folders = (glob.glob(os.path.join('{0}*'.format(self.log.photometry_directory_base))))

        def photometry_order(path):
            try:
                return float(path.split('_')[1])
            except:
                return 1

        photometry_folders = sorted(photometry_folders, key=lambda x: photometry_order(x))
        photometry_folders = ['Load options from previous run'] + photometry_folders
        self.photometry_folder_to_load = self.DropDown(initial='Load options from previous run',
                                                       instance=str,
                                                       options=photometry_folders,
                                                       width=40, command=self.load_options_from_previous_run)

        self.run_message = self.Label(text='')

        self.photometry_use_magnitude_domain = self.CheckButton(
            text=(
                'Photometrie en domaine magnitude'
            ),
            initial=_log_param_bool_safe(self.log, 'photometry_use_magnitude_domain', False),
            command=self.save_settings,
        )

        self.photometry_button = self.Button(text='RUN PHOTOMETRY', command=self.run_photometry, bg='green',
                                             highlightbackground='green')

        self.proceed_button = self.Button(text='PROCEED TO FITTING', command=self.proceed)
        if self.log.get_param('photometry_complete'):
            self.proceed_button.activate()
        else:
            self.proceed_button.disable()

        self.save_and_return_button = self.Button(text='SAVE OPTIONS & RETURN TO MAIN MENU',
                                                  command=self.save_and_return)

        self.photometry_plate_solve_button = self.Button(
            text='PLATE SOLVE IMAGE (if connected to the internet)',
            command=self.plate_solve_first)
        self.photometry_objctra_button = self.Button(
            text='Use OBJCTRA/OBJCTDEC',
            command=self.designate_target_from_header)
        ##############################################################################

        ##############################################################################
        # place widgets
        setup_list = [
            [[self.show_good_comparisons, 0],
             [self.show_good_comparisons_percent, 1],
             [self.Button(text='Check SIMBAD', command=self.openweb_simbad), 2],
             [self.Label(text="Remember, the best comparison stars need to be:\n"
                              "a) close to your target, b) of similar magnitude to the target,\n"
                              "c) of similar colour to the target, d) photometrically stable, i.e. "
                              "not variables!"), 3, 9, 2]
             ],
            [[self.photometry_use_magnitude_domain, 0, 9]],
            [[self.photometry_plate_solve_button, 0, 2],
             [self.photometry_objctra_button, 2, 1]],
            [[self.fits_figure, 0, 3, 24],],
            [[self.Label(text='Aperture\nradius (>1.5)'), 4],
             [self.Label(text='Gbp-Grp'), 6],
             [self.Label(text='Var\n(Gaia DR3)'), 7],
             [self.Label(text='SNR'), 8],
             [self.Label(text='Total\ncounts'), 9],
             [self.Label(text='Max\ncounts'), 10],
             [self.Label(text='Max\nHWHM'), 11],
             ],
        ]

        for target in self.targets:

            setup_list.append([[target[0], 3],
                               [target[1], 4],
                               [target[8], 5],
                               [target[9], 6],
                               [target[14], 7],
                               [target[18], 8],
                               [target[10], 9],
                               [target[11], 10],
                               [target[12], 11],
                               [target[13], 13]])

        setup_list += [
            [[self.show_advanced_settings_button, 7, 4]],
            [],
            [[self.photometry_folder_to_load, 3, 8]],
            [[self.Button(text='RETURN TO MAIN MENU', command=self.close), 3, 2],
             [self.save_and_return_button, 5, 6]],
            [[self.photometry_button, 3, 2],
             [self.proceed_button, 5, 6]],
            [[self.run_message, 3, 8]],
            []
        ]

        self.setup_window(setup_list, entries_wd=5)
        self._shrink_plate_solve_objctra_buttons(scale=0.7)
        self._configure_dynamic_layout()
        ##############################################################################

        self._enlarge_window_and_fit_content(scale=1.3, width_factor=0.8)
        self.update_window(None)

    def _shrink_plate_solve_objctra_buttons(self, scale=0.7):
        """Réduit police et bordure des boutons plate solve / OBJCTRA (~30 % plus petits)."""
        for hop_btn in (self.photometry_plate_solve_button, self.photometry_objctra_button):
            w = hop_btn.widget
            try:
                fn = tkfont.Font(font=w.cget('font'))
                new_sz = max(6, int(round(fn.cget('size') * scale)))
                w.configure(font=(fn.actual('family'), new_sz, fn.actual('weight')))
            except Exception:
                pass
            try:
                bd = int(w.cget('borderwidth'))
                w.configure(borderwidth=max(2, int(round(bd * scale))))
            except Exception:
                pass

    def _enlarge_window_and_fit_content(self, scale=1.3, width_factor=1.0):
        """
        Agrandit la fenêtre d'un facteur donné (par défaut +30%)
        et adapte le contenu à la nouvelle surface.
        width_factor < 1.0 réduit uniquement la largeur (ex. 0.8 = −20 %).
        """
        try:
            self.root.update_idletasks()
            req_w = max(1, int(self.root.winfo_reqwidth()))
            req_h = max(1, int(self.root.winfo_reqheight()))
            scr_w = max(1, int(self.root.winfo_screenwidth()))
            scr_h = max(1, int(self.root.winfo_screenheight()))

            wf = float(width_factor) if width_factor is not None else 1.0
            new_w = min(scr_w - 40, int(req_w * scale * wf))
            new_h = min(scr_h - 80, int(req_h * scale))
            self.root.geometry('{0}x{1}'.format(new_w, new_h))
            self.reposition()
            self.root.update_idletasks()
            # Ajuste la figure principale à la nouvelle taille de fenêtre.
            self.fits_figure.adjust_size()
        except Exception:
            pass

    def _configure_dynamic_layout(self):
        """Grille extensible + redimensionnement différé de la figure FITS (fenêtre principale)."""
        if getattr(self, 'embedded', False):
            return
        try:
            mf = self.main_frame
            self.fits_figure.widget.grid_configure(sticky='nsew')
            for col in range(14):
                mf.grid_columnconfigure(col, weight=1)
            for row in range(3, 27):
                mf.grid_rowconfigure(row, weight=1)
            self.root.bind('<Configure>', self._on_root_configure)
        except Exception:
            pass

    def _on_root_configure(self, event):
        if getattr(self, 'embedded', False):
            return
        try:
            if event.widget is not self.root:
                return
        except Exception:
            return
        self._schedule_fits_resize()

    def _schedule_fits_resize(self):
        if getattr(self, 'embedded', False):
            return
        if self._resize_after_id is not None:
            try:
                self.root.after_cancel(self._resize_after_id)
            except Exception:
                pass
        self._resize_after_id = self.root.after(120, self._apply_fits_resize)

    def _apply_fits_resize(self):
        self._resize_after_id = None
        if getattr(self, 'embedded', False):
            return
        try:
            self.fits_figure.adjust_size()
            self.fits_figure.canvas.draw_idle()
        except Exception:
            pass

    def _planet_display_name(self):
        """Libellé court : nom de la planète (ExoClock / champ planet), pas l’étoile SIMBAD."""
        p = str(self.log.get_param('planet') or '').strip()
        if p and p.lower() not in ('choose planet', 'none'):
            return p

        ra_dec_full = self.log.get_param('target_ra_dec')
        if ra_dec_full:
            ra_dec_parts = str(ra_dec_full).strip().split()
            if len(ra_dec_parts) >= 2:
                ra_s, dec_s = ra_dec_parts[0], ra_dec_parts[1]
                try:
                    def _locate():
                        return exoclock.locate_planet(
                            exoclock.Hours(ra_s),
                            exoclock.Degrees(dec_s),
                        )

                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                        fut = executor.submit(_locate)
                        planet_obj = fut.result(timeout=8)
                    if hasattr(planet_obj, 'name') and getattr(planet_obj, 'name', None):
                        return str(planet_obj.name).strip()
                    if isinstance(planet_obj, dict) and planet_obj.get('name'):
                        return str(planet_obj['name']).strip()
                except Exception:
                    pass

        sn = str(self.log.get_param('simbad_target_name') or '').strip()
        if sn:
            return sn

        s = str(self.log.get_param('target_name') or '').strip()
        for sep in (' / Host of:', '/ Host of:', ' — Host of:', '| Host of:'):
            i = s.find(sep)
            if i >= 0:
                s = s[:i].strip()
                break
        return s

    def _primary_exoclock_planet_canonical(self):
        """Nom catalogue ExoClock de la planète observée (champ planet ou plus proche du point cible)."""
        raw = str(self.log.get_param('planet') or '').strip()
        if raw and raw.lower() not in ('choose planet', 'none'):
            try:
                return exoclock.get_planet(raw)['name']
            except Exception:
                pass
        ra_dec_full = self.log.get_param('target_ra_dec')
        if not ra_dec_full:
            return None
        parts = str(ra_dec_full).strip().split()
        if len(parts) < 2:
            return None
        try:
            p = exoclock.locate_planet(
                exoclock.Hours(parts[0]),
                exoclock.Degrees(parts[1]),
                exoclock.Degrees(0.02),
            )
            return p['name']
        except Exception:
            return None

    def _plate_solve_fov_center_radius_deg(self):
        """Centre (ICRS deg) et rayon angulaire (deg) couvrant les coins du détecteur."""
        wcs = self.plate_solution['plate_solution']
        fd = self.fits_data
        h, w = len(fd), len(fd[0])
        cx, cy = w * 0.5, h * 0.5
        cxy = wcs.all_pix2world([[cx, cy]], 0)[0]
        sc_c = SkyCoord(cxy[0], cxy[1], unit='deg')
        rmax = 0.0
        for px, py in ((0, 0), (0, h), (w, 0), (w, h)):
            xy = wcs.all_pix2world([[px, py]], 0)[0]
            sc_p = SkyCoord(xy[0], xy[1], unit='deg')
            rmax = max(rmax, float(sc_c.separation(sc_p).deg))
        return float(cxy[0]), float(cxy[1]), rmax

    def _annotate_other_fov_exoclock_planets(self, psf_here):
        """Repère les autres planètes du catalogue ExoClock dont l’étoile hôte est dans le FOV."""
        try:
            ra_c, dec_c, fov_r_deg = self._plate_solve_fov_center_radius_deg()
        except Exception:
            return
        primary = self._primary_exoclock_planet_canonical()

        def _collect():
            pointing = exoclock.FixedTarget(exoclock.Degrees(ra_c), exoclock.Degrees(dec_c))
            rows = []
            for pname in exoclock.get_all_planets():
                if primary and pname == primary:
                    continue
                try:
                    pl = exoclock.get_planet(pname)
                except Exception:
                    continue
                sra = float(pl['star']['ra_deg'])
                sde = float(pl['star']['dec_deg'])
                pt = exoclock.FixedTarget(exoclock.Degrees(sra), exoclock.Degrees(sde))
                d = float(pointing.distance_on_sphere(pt).deg())
                if d <= fov_r_deg:
                    rows.append((sra, sde, pname))
            return rows

        try:
            in_fov = _collect()
        except Exception:
            return

        if not in_fov:
            return

        groups = defaultdict(list)
        for sra, sde, pname in in_fov:
            key = (round(sra, 5), round(sde, 5))
            groups[key].append(pname)

        wcs = self.plate_solution['plate_solution']
        col = '#00b4d8'
        for (sra, sde), names in sorted(groups.items(), key=lambda kv: min(kv[1])):
            names = sorted(set(names))
            label = ', '.join(names)
            try:
                px, py = SkyCoord([sra], [sde], unit='deg').to_pixel(wcs)
            except Exception:
                continue
            px0, py0 = float(px[0]), float(py[0])
            r_circ = max(2.0 * float(psf_here), 4.0)
            circ = mpatches.Circle(
                (px0 + 0.5, py0 + 0.5),
                r_circ,
                ec=col,
                fill=False,
                linewidth=1.0,
                linestyle='--',
            )
            tx = self.fits_figure.ax.text(
                px0 + 0.35 * r_circ,
                py0 + 0.5 + 0.35 * r_circ,
                label,
                color=col,
                va='bottom',
                ha='left',
                fontsize=8,
            )
            self.fits_figure.ax.add_patch(circ)
            self._plate_solve_annots.extend([circ, tx])

    def _clear_plate_solve_annots(self):
        for art in list(getattr(self, '_plate_solve_annots', [])):
            try:
                art.remove()
            except Exception:
                pass
        self._plate_solve_annots = []

    def _gaia_colour_numeric(self, x, y):
        gbp_grp, _diag, _vl, _vb = self._gaia_colour_and_diag(x, y)
        if gbp_grp == '-' or gbp_grp is None:
            return None
        try:
            return float(gbp_grp)
        except (TypeError, ValueError):
            return None

    def _aperture_from_fwhm(self, fwhm_px):
        psf = float(self.fits_header[self.log.psf_key])
        raw = float(self._fwhm_ap_scale) * float(fwhm_px)
        return float(max(round(raw, 1), round(3.0 * psf, 1)))

    def _auto_select_color_matched_comparisons(self):
        """
        Place jusqu'à 10 comparaisons : d'abord flux (counts) proche de T1,
        puis indice BP−RP Gaia ; VARIABLE exclues.
        À appeler après mise à jour du flux T1 dans update_window.
        """
        if 0 in [self.targets[0][2].get(), self.targets[0][3].get()]:
            self._t1_auto_comp_sig = None
            return False
        if not self.plate_solution:
            return False
        t_col = self._gaia_colour_numeric(self.targets[0][2].get(), self.targets[0][3].get())
        if t_col is None:
            return False

        psf = float(self.fits_header[self.log.psf_key])
        tx = float(self.targets[0][2].get())
        ty = float(self.targets[0][3].get())

        try:
            t_flux_ref = float(self.targets[0][10].get())
        except Exception:
            t_flux_ref = 0.0
        if not np.isfinite(t_flux_ref) or t_flux_ref <= 0:
            best_d = 1e99
            nearest_flux = None
            for row in self.all_stars:
                dd = np.hypot(float(row[0]) - tx, float(row[1]) - ty)
                if dd < best_d:
                    best_d = dd
                    nearest_flux = float(row[7])
            if best_d <= 3.0 * psf and nearest_flux is not None and nearest_flux > 0:
                t_flux_ref = nearest_flux
            else:
                return False

        sig = (
            round(float(self.targets[0][2].get()), 1),
            round(float(self.targets[0][3].get()), 1),
            round(t_col, 3),
            round(float(t_flux_ref), 3),
        )
        if sig == self._t1_auto_comp_sig:
            return False
        self._t1_auto_comp_sig = sig

        candidates = []
        for j, comp_star in enumerate(self.all_stars):
            try:
                if not self.in_fov[j]:
                    continue
            except Exception:
                continue
            cx, cy = float(comp_star[0]), float(comp_star[1])
            if np.hypot(cx - tx, cy - ty) <= 3.0 * psf:
                continue
            gbp_grp, _d, var_lbl, _blink = self._gaia_colour_and_diag(cx, cy)
            if gbp_grp == '-':
                continue
            try:
                ccol = float(gbp_grp)
            except (TypeError, ValueError):
                continue
            if str(var_lbl).strip().upper() == 'VAR':
                continue
            flux = comp_star[7]
            try:
                f_comp = float(flux)
                if f_comp <= 0:
                    continue
            except Exception:
                continue
            dflux = abs(f_comp - t_flux_ref) / max(t_flux_ref, 1e-30)
            dcol = abs(ccol - t_col)
            dist = np.hypot(cx - tx, cy - ty)
            candidates.append((dflux, dcol, dist, cx, cy))

        candidates.sort(key=lambda z: (z[0], z[1], z[2]))
        n_fill = min(10, len(candidates), self.max_targets - 1)
        for k in range(n_fill):
            __df, _dc, _dist, cx, cy = candidates[k]
            self.targets[k + 1][2].set(round(cx, 1))
            self.targets[k + 1][3].set(round(cy, 1))
            self.targets[k + 1][10].set(0)
            self.targets[k + 1][1].set(0)
        for slot in range(n_fill + 1, self.max_targets):
            self.targets[slot][2].set(0.0)
            self.targets[slot][3].set(0.0)
            self.targets[slot][10].set(0)
            self.targets[slot][1].set(0)

        return n_fill > 0

    def _read_header_target_coord(self):
        """Lit OBJCTRA/OBJCTDEC (ou RA/DEC) et retourne une SkyCoord ou None."""
        try:
            header = self.fits_header
            ra_h = header.get("OBJCTRA") or header.get("RA")
            dec_h = header.get("OBJCTDEC") or header.get("DEC")
            if ra_h is None or dec_h is None:
                return None

            # Cas 1: valeurs numériques (deg ou hour)
            try:
                ra_val = float(ra_h)
                dec_val = float(dec_h)
                if ra_val > 24.0:
                    return SkyCoord(ra_val, dec_val, unit=("deg", "deg"), frame='icrs')
            except Exception:
                pass

            # Cas 2: format sexagésimal (HH:MM:SS / DD:MM:SS)
            try:
                return SkyCoord(ra_h, dec_h, unit=("hourangle", "deg"), frame='icrs')
            except Exception:
                return SkyCoord(float(ra_h), float(dec_h), unit=("deg", "deg"), frame='icrs')

        except Exception:
            return None

    def designate_target_from_header(self):
        """
        Utilise OBJCTRA/OBJCTDEC pour désigner T1.
        - Si WCS dispo: projection RA/Dec -> pixel et placement direct de T1.
        - Sinon: met à jour target_ra_dec pour faciliter le plate solve.
        """
        coord = self._read_header_target_coord()
        if coord is None:
            self.showinfo('Target designation',
                          'OBJCTRA/OBJCTDEC (ou RA/DEC) introuvables dans le header FITS.')
            return

        # Toujours mettre à jour target_ra_dec pour la cohérence (SIMBAD / plate solve)
        ra_txt = coord.ra.to_string(unit='hour', sep=':', precision=2, pad=True)
        dec_txt = coord.dec.to_string(unit='deg', sep=':', precision=1, pad=True, alwayssign=True)
        self.log.set_param('target_ra_dec', '{0} {1}'.format(ra_txt, dec_txt))

        try:
            wcs = WCS(self.fits_header)
            tx, ty = wcs.world_to_pixel(coord)
            if not np.isfinite(tx) or not np.isfinite(ty):
                raise ValueError('Projection WCS invalide')

            # Conversion vers repère HOPS (pixels centrés à +0.5)
            x = float(tx) + 0.5
            y = float(ty) + 0.5

            if x < 1 or x > len(self.fits_data[0]) or y < 1 or y > len(self.fits_data):
                raise ValueError('Cible hors image')

            # Raffinage sur l'étoile locale si possible
            star = self.get_star(x, y)
            if star:
                x, y = star[0], star[1]

            self.targets_indication.set(0)
            self.targets[0][2].set(round(x, 1))
            self.targets[0][3].set(round(y, 1))
            self.targets[0][10].set(0)
            self.update_window(None)
            self.showinfo('Target designation',
                          'Cible T1 positionnée depuis OBJCTRA/OBJCTDEC.')
        except Exception:
            self.showinfo('Target designation',
                          'RA/Dec lues depuis le header.\n'
                          'WCS indisponible pour positionner T1 automatiquement.\n'
                          'Utilisez maintenant "PLATE SOLVE IMAGE".')

    def get_star(self, x, y):

        star = image_find_stars(
            self.fits_data, self.fits_header,
            x_low=x - 3 * self.fits_header[self.log.psf_key],
            x_upper=x + 3 * self.fits_header[self.log.psf_key],
            y_low=y - 3 * self.fits_header[self.log.psf_key],
            y_upper=y + 3 * self.fits_header[self.log.psf_key],
            x_centre=x,
            y_centre=y,
            mean=self.fits_header[self.log.mean_key],
            std=self.fits_header[self.log.std_key],
            burn_limit=self.fits_header[self.log.hops_saturation_key] * self.saturation.get(),
            psf=self.fits_header[self.log.psf_key],
            centroids_snr=self.centroids_snr, stars_snr=self.stars_snr,
            order_by_flux=False,
        )

        if not star:
            return None

        else:
            star = star[0]
            app = round(3 * self.fits_header[self.log.psf_key], 1)
            x = round(star[0], 1)
            y = round(star[1], 1)

            x1 = int(star[0] - app)
            x2 = x1 + int(2 * app) + 2
            y1 = int(star[1] - app)
            y2 = y1 + int(2 * app) + 2

            peak = round(np.max(self.fits_data[y1:y2, x1:x2]), 1)

            flux = round(star[7], 1)

            max_hwhm = round(0.5 * 2.355 * max(star[4], star[5]), 1)
            fwhm_px = round(2.355 * max(star[4], star[5]), 2)

            x1 = int(star[0] - 3 * self.fits_header[self.log.psf_key])
            x2 = x1 + int(6 * self.fits_header[self.log.psf_key]) + 1
            y1 = int(star[1] - 3 * self.fits_header[self.log.psf_key])
            y2 = y1 + int(6 * self.fits_header[self.log.psf_key]) + 1

            area = self.fits_data[y1:y2, x1:x2]

            area_x, area_y = np.meshgrid(
                np.arange(x1, x2) + 0.5,
                np.arange(y1, y2) + 0.5)

            wx = (round(np.sum(area_x * area) / np.sum(area), 1))
            wy = (round(np.sum(area_y * area) / np.sum(area), 1))

            return x, y, app, peak, flux, max_hwhm, wx, wy, fwhm_px

    def select_star(self, event=None):

        if isinstance(event, matplotlib.backend_bases.MouseEvent):

            if event.inaxes is None:
                return None

            if event.dblclick:

                star = self.get_star(event.xdata, event.ydata)

                if not star:
                    self.showinfo('Star not acceptable.', 'Star could not be located or it includes pixels above the saturation limit.')
                    return None

                else:

                    x, y, app, peak, flux, max_hwhm, wx, wy, _fh = star

                    if (x < self.visible_fov_x_min or x > self.visible_fov_x_max
                            or y < self.visible_fov_y_min or y > self.visible_fov_y_max):

                        self.showinfo('Star not acceptable.', 'Star moves outside the FOV later.')
                        return None

                    else:

                        self.targets[self.targets_indication.get()][2].set(x)
                        self.targets[self.targets_indication.get()][3].set(y)
                        self.targets[self.targets_indication.get()][10].set(0)

                        self.update_window(None)

            else:
                return None

    def load_options_from_previous_run(self):

        try:

            other_log = self.log.open_yaml(os.path.join(self.photometry_folder_to_load.get(), 'log.yaml'))

            for parameter in [
                [self.use_variable_aperture, 'use_variable_aperture'],
                [self.use_geometric_center, 'use_geometric_center'],
                [self.sky_inner_aperture, 'sky_inner_aperture'],
                [self.sky_outer_aperture, 'sky_outer_aperture'],
                [self.saturation, 'saturation'],
                [self.show_good_comparisons, 'show_good_comparisons'],
                [self.show_good_comparisons_percent, 'show_good_comparisons_percent']
            ]:

                try:
                    parameter[0].set(other_log[parameter[1]])
                except:
                    parameter[0].set(self.log.get_param(parameter[1]))

            self.targets_indication.set(0)

            try:
                self.targets[0][1].set(other_log['target_aperture'])
                self.targets[0][2].set(other_log['target_x_position'])
                self.targets[0][3].set(other_log['target_y_position'])
                self.targets[0][10].set(0)
            except:
                self.targets[0][1].set(0)
                self.targets[0][2].set(0)
                self.targets[0][3].set(0)
                self.targets[0][10].set(0)

            for comparison in range(1, self.max_targets):

                try:
                    self.targets[comparison][1].set(other_log['comparison_{0}_aperture'.format(comparison)])
                    self.targets[comparison][2].set(other_log['comparison_{0}_x_position'.format(comparison)])
                    self.targets[comparison][3].set(other_log['comparison_{0}_y_position'.format(comparison)])
                    self.targets[comparison][10].set(0)
                except:
                    self.targets[comparison][1].set(0)
                    self.targets[comparison][2].set(0)
                    self.targets[comparison][3].set(0)
                    self.targets[comparison][10].set(0)

            self.update_window(None)

        except FileNotFoundError:
            pass

    def _parse_gaia_variable_flag(self, raw):
        """
        phot_variable_flag Gaia DR3 : typiquement VARIABLE, CONSTANT, NOT_AVAILABLE.
        Retourne (libellé court, clignoter si comparaison variable).
        """
        if raw is None:
            return '-', False
        try:
            if isinstance(raw, (float, np.floating)) and np.isnan(raw):
                return '-', False
        except Exception:
            pass
        s = str(raw).strip().upper()
        if s == 'VARIABLE':
            return 'VAR', True
        if s == 'CONSTANT':
            return 'const', False
        if s in ('NOT_AVAILABLE', 'NOT AVAILABLE', 'N/A', ''):
            return 'n/a', False
        if s == 'TRUE' or raw is True:
            return 'VAR', True
        return (s[:10] if s else '-'), False

    def _gaia_colour_and_diag(self, x, y):
        """
        Retourne (gbp_grp, diagnostic, libellé_var_gaia, est_variable_pour_clignotement).
        gbp_grp est '-' si non disponible.
        """
        if not self.plate_solution:
            return '-', 'No plate solve', '-', False

        identified = self.plate_solution.get('identified_stars', {})
        if not identified:
            return '-', 'Gaia list empty', '-', False

        identified_stars = [[ii, identified[ii].get('x'), identified[ii].get('y')] for ii in identified]
        identified_stars = [row for row in identified_stars if row[1] is not None and row[2] is not None]
        if not identified_stars:
            return '-', 'Gaia x/y missing', '-', False

        match_gaia_id = sorted(
            identified_stars,
            key=lambda row: np.sqrt((x - row[1]) ** 2 + (y - row[2]) ** 2)
        )[0][0]
        match = identified.get(match_gaia_id, {})
        v_lbl, v_blink = self._parse_gaia_variable_flag(match.get('phot_variable_flag'))

        dist = np.sqrt((x - match.get('x', 1e9)) ** 2 + (y - match.get('y', 1e9)) ** 2)
        max_dist = 3 * self.fits_header[self.log.psf_key]
        if dist >= max_dist:
            return '-', 'Gaia too far ({0:.1f}px)'.format(dist), '-', False

        bp = match.get('phot_bp_mean_mag')
        rp = match.get('phot_rp_mean_mag')
        try:
            if bp is None or rp is None or (not np.isfinite(bp)) or (not np.isfinite(rp)):
                return '-', 'Gaia BP/RP missing', v_lbl, v_blink
            return round(bp - rp, 2), 'Gaia OK', v_lbl, v_blink
        except Exception:
            return '-', 'Gaia BP/RP invalid', v_lbl, v_blink

    def _variable_blink_tick(self):
        if not self._root_alive():
            self._variable_blink_scheduled = False
            return

        any_var = False
        for i in range(1, self.max_targets):
            if self.targets[i][15] and 0 not in [self.targets[i][2].get(), self.targets[i][3].get()]:
                any_var = True
                break

        if not any_var:
            self._variable_blink_scheduled = False
            for i in range(1, self.max_targets):
                if 0 in [self.targets[i][2].get(), self.targets[i][3].get()]:
                    continue
                for idx in (4, 5, 6):
                    self.targets[i][idx].set_edgecolor('#07fefc')
                self.targets[i][7].set_color('#07fefc')
            try:
                self.fits_figure.canvas.draw_idle()
            except Exception:
                pass
            return

        self._variable_blink_phase ^= 1
        col = '#ff6600' if self._variable_blink_phase else '#07fefc'
        for i in range(1, self.max_targets):
            if 0 in [self.targets[i][2].get(), self.targets[i][3].get()]:
                continue
            if self.targets[i][15]:
                for idx in (4, 5, 6):
                    self.targets[i][idx].set_edgecolor(col)
                self.targets[i][7].set_color(col)
            else:
                for idx in (4, 5, 6):
                    self.targets[i][idx].set_edgecolor('#07fefc')
                self.targets[i][7].set_color('#07fefc')

        try:
            self.fits_figure.canvas.draw_idle()
        except Exception:
            pass
        self.after(self._variable_blink_tick, time=550)

    def update_window(self, event=None):

        # update targets

        for i_target in range(self.max_targets):

            if 0 in [self.targets[i_target][2].get(), self.targets[i_target][3].get()]:

                self.targets[i_target][1].disable()
                self.targets[i_target][1].set(0)
                self.targets[i_target][2].set(0)
                self.targets[i_target][3].set(0)
                self.targets[i_target][4].set_center((-10000, -10000))
                self.targets[i_target][5].set_center((-10000, -10000))
                self.targets[i_target][6].set_center((-10000, -10000))
                self.targets[i_target][7].set_x(-10000)
                self.targets[i_target][7].set_y(-10000)
                self.targets[i_target][9].set('-')
                self.targets[i_target][10].set(0)
                self.targets[i_target][11].set(0)
                self.targets[i_target][12].set(0)
                self.targets[i_target][13].set('')
                self.targets[i_target][14].set('-')
                self.targets[i_target][15] = False
                self.targets[i_target][16] = 0
                self.targets[i_target][17] = 0
                self.targets[i_target][18].set('-')

            else:

                self.targets[i_target][1].activate()

                if self.targets[i_target][10].get() == 0:

                    star = self.get_star(self.targets[i_target][2].get(),
                                         self.targets[i_target][3].get())

                    if not star:
                        xx = self.clear_target(i_target)
                        return xx()

                    else:

                        x, y, app, peak, flux, max_hwhm, wx, wy, fwhm_px = star

                        if self.targets[i_target][1].get() == 0:
                            self.targets[i_target][1].set(self._aperture_from_fwhm(fwhm_px))
                        self.targets[i_target][2].set(x)
                        self.targets[i_target][3].set(y)
                        self.targets[i_target][9].set('-')
                        self.targets[i_target][10].set(flux)
                        self.targets[i_target][11].set(peak)
                        self.targets[i_target][12].set(max_hwhm)
                        gain = self.camera_gain.get()
                        if gain is None or (not np.isfinite(gain)) or gain <= 0:
                            self.targets[i_target][18].set('-')
                        else:
                            snr_den = np.sqrt(np.abs(flux) / gain)
                            snr = flux / max(snr_den, 1e-30)
                            self.targets[i_target][18].set(round(snr, 2))
                        self.targets[i_target][16] = wx
                        self.targets[i_target][17] = wy

                if self.use_geometric_center.get():
                    self.targets[i_target][4].set_center((self.targets[i_target][16], self.targets[i_target][17]))
                    self.targets[i_target][5].set_center((self.targets[i_target][16], self.targets[i_target][17]))
                    self.targets[i_target][6].set_center((self.targets[i_target][16], self.targets[i_target][17]))
                else:
                    self.targets[i_target][4].set_center((self.targets[i_target][2].get(), self.targets[i_target][3].get()))
                    self.targets[i_target][5].set_center((self.targets[i_target][2].get(), self.targets[i_target][3].get()))
                    self.targets[i_target][6].set_center((self.targets[i_target][2].get(), self.targets[i_target][3].get()))

                self.targets[i_target][4].set_radius(self.targets[i_target][1].get())
                self.targets[i_target][5].set_radius(self.targets[i_target][1].get() * self.sky_inner_aperture.get())
                self.targets[i_target][5].set_linestyle(":")
                self.targets[i_target][6].set_radius(self.targets[i_target][1].get() * self.sky_outer_aperture.get())
                self.targets[i_target][6].set_linestyle(":")

                fov_options = self.fits_figure.get_fov_options()
                text_y_drift = [-1, 1][int(fov_options[3])]
                text_x_drift = [1, -1][int(fov_options[4])]

                self.targets[i_target][7].set_x(self.targets[i_target][2].get() + text_x_drift * self.targets[i_target][1].get())
                self.targets[i_target][7].set_y(self.targets[i_target][3].get() + text_y_drift * self.targets[i_target][1].get())

                gbp_grp, diag, var_lbl, is_gaia_var = self._gaia_colour_and_diag(
                    self.targets[i_target][2].get(),
                    self.targets[i_target][3].get()
                )
                self.targets[i_target][9].set(gbp_grp)
                if i_target == 0:
                    self.targets[0][14].set('-')
                    self.targets[0][15] = False
                else:
                    self.targets[i_target][14].set(var_lbl)
                    self.targets[i_target][15] = is_gaia_var
                # Colonne diagnostic (utile pour comprendre pourquoi Gbp-Grp reste '-')
                self.targets[i_target][13].set(diag if diag != 'Gaia OK' else '')

        if (
            self._auto_select_color_matched_comparisons()
            and not self._auto_comp_refresh_scheduled
        ):
            self._auto_comp_refresh_scheduled = True

            def _refresh_after_auto():
                self._auto_comp_refresh_scheduled = False
                try:
                    self.update_window(None)
                except Exception:
                    pass

            self.after(_refresh_after_auto, time=15)

        # update good comparisons

        if 0 not in [self.targets[0][2].get(), self.targets[0][3].get()]:

            good_comps = []

            for j, comp_star in enumerate(self.all_stars):
                if np.sqrt((comp_star[0] - self.targets[0][2].get())**2 +
                           (comp_star[1] - self.targets[0][3].get())**2) > 3 * self.fits_header[self.log.psf_key]:
                    if self.in_fov[j]:
                        if comp_star[7] < (1 + self.show_good_comparisons_percent.get() / 100) * self.targets[0][10].get():
                            if comp_star[7] > (1 - self.show_good_comparisons_percent.get() / 100) * self.targets[0][10].get():
                                good_comps.append(comp_star)

            good_comps = sorted(good_comps,
                                key=lambda x: np.sqrt((x[0] -
                                                       self.targets[0][2].get()) ** 2 +
                                                      (x[1] -
                                                       self.targets[0][2].get()) ** 2))

            for num in range(100):

                if num < len(good_comps):
                    self.good_comps_boxes[num].set_xy((good_comps[num][0] - 5 * self.fits_header[self.log.psf_key],
                                                        good_comps[num][1] - 5 * self.fits_header[self.log.psf_key]))
                else:
                    self.good_comps_boxes[num].set_xy((-1000, -1000))

                if not self.show_good_comparisons.get():
                    self.good_comps_boxes[num].set_alpha(0)
                else:
                    self.good_comps_boxes[num].set_alpha(1)

        # update warnings

        if 0 not in [self.targets[0][2].get(), self.targets[0][3].get()]:
            for i_target in range(1, self.max_targets):
                if 0 not in [self.targets[i_target][2].get(), self.targets[i_target][3].get()]:
                    if self.targets[i_target][10].get() > 2 * self.targets[0][10].get():
                        msg = 'Comp. too bright'
                    elif self.targets[i_target][10].get() < 0.5 * self.targets[0][10].get():
                        msg = 'Comp. too faint'
                    else:
                        msg = ''
                    diag = self.targets[i_target][13].get()
                    if msg:
                        combo = '{0}\n{1}'.format(msg, diag) if diag else msg
                        self.targets[i_target][13].set(combo.strip())

        # update action buttons
        photometry_active = True

        self.run_message.set('')
        for i_target in range(self.max_targets):
            if 0 not in [self.targets[i_target][2].get(), self.targets[i_target][3].get()]:
                if self.targets[i_target][1].get() < 1.5:
                    photometry_active = False
                    self.run_message.set('All aperture radii must be larger than 1.5 pixels')

        if 0 in [self.targets[0][2].get(), self.targets[0][3].get(),
                 self.targets[1][2].get(), self.targets[1][3].get()]:
            self.run_message.set('You need to select the target and at least one comparison star to proceed.')
            photometry_active = False

        if self.sky_inner_aperture.get() <= 1.0 or self.sky_outer_aperture.get() <= 1.0:
            self.run_message.set('Inner and outer sky-ring radii must be larger than 1.')
            photometry_active = False

        if self.sky_inner_aperture.get() >= self.sky_outer_aperture.get():
            self.run_message.set('Inner sky-ring radius must be smaller than the outer sky-ring radius.')
            photometry_active = False

        if self.saturation.get() <= 0:
            self.run_message.set('Saturation limit must be larger than 0.')
            photometry_active = False

        if self.saturation.get() > 1:
            self.run_message.set('Saturation limit must be lower or equal to 1.')
            photometry_active = False

        if photometry_active:
            self.photometry_button.activate()
            self.save_and_return_button.activate()
        else:
            self.photometry_button.disable()
            self.save_and_return_button.disable()

        for i_target in range(self.max_targets):
            self.targets[i_target][0]['state'] = self.DISABLED
        for i_target in range(self.max_targets):
            if 0 not in [self.targets[i_target][2].get(), self.targets[i_target][3].get()]:
                self.targets[i_target][0]['state'] = self.NORMAL
            else:
                self.targets[i_target][0]['state'] = self.NORMAL
                break

        for i in range(1, self.max_targets):
            if 0 in [self.targets[i][2].get(), self.targets[i][3].get()]:
                continue
            if not self.targets[i][15]:
                for idx in (4, 5, 6):
                    self.targets[i][idx].set_edgecolor('#07fefc')
                self.targets[i][7].set_color('#07fefc')

        any_var_comp = False
        for i in range(1, self.max_targets):
            if self.targets[i][15] and 0 not in [self.targets[i][2].get(), self.targets[i][3].get()]:
                any_var_comp = True
                break
        if any_var_comp and not self._variable_blink_scheduled:
            self._variable_blink_scheduled = True
            self.after(self._variable_blink_tick, time=550)
        elif not any_var_comp:
            self._variable_blink_scheduled = False

        self.fits_figure.draw()

    # define actions for the different buttons, including calls to the function that updates the window

    def clear_target(self, num):

        def clear_target_num():

            self.targets[num][2].set(0.0)
            self.targets[num][3].set(0.0)

            for i_target in range(1, self.max_targets - 1):
                if self.targets[i_target][2].get() == 0 and self.targets[i_target + 1][2].get() != 0:

                    self.targets[i_target][1].set(self.targets[i_target + 1][1].get())
                    self.targets[i_target][2].set(self.targets[i_target + 1][2].get())
                    self.targets[i_target][3].set(self.targets[i_target + 1][3].get())
                    self.targets[i_target][10].set(0)

                    self.targets[i_target + 1][1].set(0.0)
                    self.targets[i_target + 1][2].set(0.0)
                    self.targets[i_target + 1][3].set(0.0)

            self.targets_indication.set(0)
            self.update_window(None)

        return clear_target_num

    def openweb_simbad(self):

        radec_string = self.log.get_param('target_ra_dec').replace('+', '%2B').replace(' ', '+')
        webbrowser.open("http://simbad.u-strasbg.fr/simbad/sim-coo?Coord={0}&CooFrame=ICRS&"
                        "CooEpoch=2000&CooEqui=2000&CooDefinedFrames=none&Radius=20&"
                        "Radius.unit=arcmin&submit=submit+query&CoordList=".format(radec_string), new=1)

    def plate_solve_first(self):

        ra_target, dec_target = self.log.get_param('target_ra_dec').split(' ')
        ra = exoclock.Hours(ra_target).deg()
        dec = exoclock.Degrees(dec_target).deg_coord()

        try:

            if self.plate_solution is None:

                try:

                    self.plate_solution = image_plate_solve(self.fits_data, self.fits_header, ra, dec,
                                                            mean=self.fits_header[self.log.mean_key],
                                                            std=self.fits_header[self.log.std_key],
                                                            burn_limit=self.fits_header[self.log.hops_saturation_key],
                                                            psf=self.fits_header[self.log.psf_key],
                                                            stars=self.all_stars,
                                                            pixel=0.5 * self.star_size_arcsec.get() / self.fits_header[self.log.psf_key],
                                                            verbose=True)

                    if len(self.plate_solution['identified_stars']) < 0.5 * len(self.all_stars):
                        print('Only {0} / {1} stars identified, solution rejected'.format(
                            len(self.plate_solution['identified_stars']), len(self.all_stars)))
                        self.plate_solution = None

                except:
                    print('Solution failed.')
                    pass

            if self.plate_solution is None:

                try:

                    self.plate_solution = image_plate_solve(self.fits_data, self.fits_header, ra, dec,
                                                            mean=self.fits_header[self.log.mean_key],
                                                            std=self.fits_header[self.log.std_key],
                                                            burn_limit=self.fits_header[self.log.hops_saturation_key],
                                                            psf=self.fits_header[self.log.psf_key],
                                                            stars=self.all_stars,
                                                            pixel=0.25 * self.star_size_arcsec.get() / self.fits_header[self.log.psf_key],
                                                            verbose=True)

                    if len(self.plate_solution['identified_stars']) < 0.5 * len(self.all_stars):
                        print('Only {0} / {1} stars identified, solution rejected'.format(
                            len(self.plate_solution['identified_stars']), len(self.all_stars)))
                        self.plate_solution = None

                except:
                    print('Solution failed.')
                    pass

            if self.plate_solution is None:

                try:

                    self.plate_solution = image_plate_solve(self.fits_data, self.fits_header, ra, dec,
                                                            mean=self.fits_header[self.log.mean_key],
                                                            std=self.fits_header[self.log.std_key],
                                                            burn_limit=self.fits_header[self.log.hops_saturation_key],
                                                            psf=self.fits_header[self.log.psf_key],
                                                            stars=self.all_stars,
                                                            pixel=1.0 * self.star_size_arcsec.get() / self.fits_header[self.log.psf_key],
                                                            verbose=True)

                    if len(self.plate_solution['identified_stars']) < 0.5 * len(self.all_stars):
                        print('Only {0} / {1} stars identified, solution rejected'.format(
                            len(self.plate_solution['identified_stars']), len(self.all_stars)))
                        self.plate_solution = None

                except:
                    print('Solution failed.')
                    pass

        except:
            self.log.debug()
            pass

        if self.plate_solution is None:
            self.showinfo('Plate solution failed',
                          'Plate solution failed. Please check your internet connection and the '
                          '"Star FWHM in arcseonds" value, under the "Advanced settings".')

        else:

            target_x, target_y = SkyCoord([[ra, dec]], unit="deg").to_pixel(self.plate_solution['plate_solution'])
            self._clear_plate_solve_annots()
            dd = len(self.fits_data[0]) * 0.035
            psf_here = float(self.fits_header[self.log.psf_key])
            bx = dd * 1.414
            arrow = mpatches.Arrow(
                target_x[0] - 2.2 * psf_here - bx,
                target_y[0] - 2.2 * psf_here - bx,
                bx, bx, width=max(bx / 8.0, 0.4), color='r')

            text = self._planet_display_name()
            ta = self.fits_figure.ax.text(
                target_x[0] - 0.22 * bx, target_y[0] - 0.25 * bx,
                text, color='r', va='top', ha='left', fontsize=10)
            self.fits_figure.ax.add_patch(arrow)
            self._plate_solve_annots.extend([arrow, ta])
            self._annotate_other_fov_exoclock_planets(psf_here)

            # for ii in self.plate_solution['identified_stars']:
            #     circle = mpatches.Circle((self.plate_solution['identified_stars'][ii]['x'] + 0.5,
            #                               self.plate_solution['identified_stars'][ii]['y'] + 0.5),
            #                              6 * self.fits_header[self.log.psf_key], ec='w', fill=False)
            #     self.fits_figure.ax.add_patch(circle)

            self.update_window()

    def save_settings(self):

        self.log.set_param('show_good_comparisons', self.show_good_comparisons.get())
        self.log.set_param('show_good_comparisons_percent', self.show_good_comparisons_percent.get())
        self.log.set_param('show_good_comparisons_percent', self.show_good_comparisons_percent.get())
        self.log.set_param('sky_inner_aperture', self.sky_inner_aperture.get())
        self.log.set_param('sky_outer_aperture', self.sky_outer_aperture.get())
        self.log.set_param('star_size_arcsec', self.star_size_arcsec.get())
        self.log.set_param('saturation', self.saturation.get())
        self.log.set_param('camera_gain', self.camera_gain.get())
        self.log.set_param('use_variable_aperture', self.use_variable_aperture.get())
        self.log.set_param('use_geometric_center', self.use_geometric_center.get())
        self.log.set_param('photometry_fov_options', self.fits_figure.get_fov_options())
        self.log.set_param('photometry_use_magnitude_domain', self.photometry_use_magnitude_domain.get())

        # targets

        targets = 1

        self.log.set_param('target_x_position', self.targets[0][2].get())
        self.log.set_param('target_y_position', self.targets[0][3].get())
        self.log.set_param('target_aperture', self.targets[0][1].get())
        target_polar = cartesian_to_polar(self.targets[0][2].get(), self.targets[0][3].get(),
                                              self.fits_header[self.log.align_x0_key],
                                              self.fits_header[self.log.align_y0_key])
        self.log.set_param('target_r_position', float(target_polar[0]))
        self.log.set_param('target_u_position', float(target_polar[1]))

        for comparison in range(1, self.max_targets):
            self.log.set_param('comparison_{0}_x_position'.format(comparison),
                               self.targets[comparison][2].get())
            self.log.set_param('comparison_{0}_y_position'.format(comparison),
                               self.targets[comparison][3].get())
            self.log.set_param('comparison_{0}_aperture'.format(comparison),
                               self.targets[comparison][1].get())

            if 0 not in [self.targets[comparison][2].get(),
                         self.targets[comparison][3].get()]:

                target_polar = cartesian_to_polar(self.targets[comparison][2].get(),
                                                      self.targets[comparison][3].get(),
                                                      self.fits_header[self.log.align_x0_key],
                                                      self.fits_header[self.log.align_y0_key])
                targets += 1

            else:

                target_polar = [0, 0]

            self.log.set_param('comparison_{0}_r_position'.format(comparison), float(target_polar[0]))
            self.log.set_param('comparison_{0}_u_position'.format(comparison), float(target_polar[1]))

        self.targets_indication.set(0)

        # save log

        self.log.save_local_log()

    def save_and_return(self):

        self.save_settings()

        self.close()

    def run_photometry(self):

        self.save_settings()

        self.log.set_param('proceed', 'run_photometry')
        self.close()

    def proceed(self):
        self.log.set_param('proceed', True)
        self.close()


class PhotometryProgressWindow(MainWindow):

    def __init__(self, log):

        MainWindow.__init__(self, log, name='HOPS - Photometry progress', position=2)

        # load variabvles

        self.bin_fits = self.log.get_param('bin_fits')
        self.saturation = self.log.get_param('saturation')
        self.max_targets = self.log.get_param('max_comparisons') + 1
        self.target_ra_dec = self.log.get_param('target_ra_dec')
        self.visible_fov_x_min = self.log.get_param('min_x')
        self.visible_fov_y_min = self.log.get_param('min_y')
        self.visible_fov_x_max = self.log.get_param('max_x')
        self.visible_fov_y_max = self.log.get_param('max_y')
        self.use_geometric_center = self.log.get_param('use_geometric_center')
        self.use_variable_aperture = self.log.get_param('use_variable_aperture')
        self.sky_inner_aperture = self.log.get_param('sky_inner_aperture')
        self.sky_outer_aperture = self.log.get_param('sky_outer_aperture')
        self.camera_gain = self.log.get_param('camera_gain')
        self.faint_target_mode = self.log.get_param('faint_target_mode')
        self.moving_target_mode = self.log.get_param('moving_target_mode')
        self.centroids_snr = self.log.get_param('centroids_snr')
        self.stars_snr = self.log.get_param('stars_snr')

        # load science files and targets

        self.all_frames = plc.open_dict(self.log.all_frames)
        self.science_files = []
        self.exposure_time = []

        for science_file in self.all_frames:
            if not self.all_frames[science_file][self.log.skip_key]:
                self.science_files.append(science_file)
                self.exposure_time.append(self.all_frames[science_file][self.log.get_param('exposure_time_key')])

        self.exposure_time = np.median(self.exposure_time)
        self.science_files.sort()

        self.first_fits_data, self.first_fits_header = get_fits_data_and_header(os.path.join(self.log.reduction_directory, self.science_files[0]))

        self.jd = []
        self.file_names = []
        self.psf_ratio = []
        for science_file in self.science_files:
            metadata = self.all_frames[science_file]
            self.jd.append(metadata[self.log.time_key])
            self.file_names.append(science_file)
            self.psf_ratio.append(metadata[self.log.psf_key])

        if self.use_variable_aperture:
            self.psf_ratio = np.array(self.psf_ratio) / self.psf_ratio[0]
        else:

            self.psf_ratio = np.ones_like(self.psf_ratio)

        self.targets_aperture = [self.log.get_param('target_aperture')]
        self.targets_x_position = [self.log.get_param('target_x_position')]
        self.targets_y_position = [self.log.get_param('target_y_position')]
        self.targets_r_position = [self.log.get_param('target_r_position')]
        self.targets_u_position = [self.log.get_param('target_u_position')]

        for comparison in range(1, self.max_targets):
            if 0 not in [self.log.get_param('comparison_{0}_x_position'.format(comparison)),
                         self.log.get_param('comparison_{0}_y_position'.format(comparison))]:
                self.targets_aperture.append(self.log.get_param('comparison_{0}_aperture'.format(comparison)))
                self.targets_x_position.append(self.log.get_param('comparison_{0}_x_position'.format(comparison)))
                self.targets_y_position.append(self.log.get_param('comparison_{0}_y_position'.format(comparison)))
                self.targets_r_position.append(self.log.get_param('comparison_{0}_r_position'.format(comparison)))
                self.targets_u_position.append(self.log.get_param('comparison_{0}_u_position'.format(comparison)))

        self.targets = len(self.targets_aperture)
        self.max_aperture = np.max(self.targets_aperture)

        # results placeholder

        self.results = {
            'jd': np.array(self.jd),
            'file_names': np.array(self.file_names),
            'gauss_x_position': np.array([[np.nan for fff in self.science_files] for ff in range(self.targets)]),
            'gauss_y_position': np.array([[np.nan for fff in self.science_files] for ff in range(self.targets)]),
            'gauss_x_std': np.array([[np.nan for fff in self.science_files] for ff in range(self.targets)]),
            'gauss_y_std': np.array([[np.nan for fff in self.science_files] for ff in range(self.targets)]),
            'gauss_flux': np.array([[np.nan for fff in self.science_files] for ff in range(self.targets)]),
            'gauss_flux_error': np.array([[np.nan for fff in self.science_files] for ff in range(self.targets)]),
            'gauss_sky': np.array([[np.nan for fff in self.science_files] for ff in range(self.targets)]),
            'gauss_sky_error': np.array([[np.nan for fff in self.science_files] for ff in range(self.targets)]),
            'aperture_x_position': np.array([[np.nan for fff in self.science_files] for ff in range(self.targets)]),
            'aperture_y_position': np.array([[np.nan for fff in self.science_files] for ff in range(self.targets)]),
            'aperture_flux': np.array([[np.nan for fff in self.science_files] for ff in range(self.targets)]),
            'aperture_flux_error': np.array([[np.nan for fff in self.science_files] for ff in range(self.targets)]),
            'aperture_background': np.array([[np.nan for fff in self.science_files] for ff in range(self.targets)]),
            'aperture_background_error': np.array([[np.nan for fff in self.science_files] for ff in range(self.targets)]),
        }

        self.results_saved = False

        # progress figure

        self.progress_figure = self.FigureWindow()

        self.axes_fits = []
        self.circles_fits = []
        self.images_fits = []
        self.star_image_lim = int(1.5 * np.max(self.max_aperture) + 5)
        self.star_plot_lim = 1.5 * np.max(self.max_aperture)
        self.axes_lc = []
        self.images_text_lc = []
        self.images_gauss_lc = []
        self.images_aperture_lc = []
        self._lc_plot_is_mag = _log_param_bool_safe(self.log, 'photometry_use_magnitude_domain', False)
        self.axes_lc_ylims = [-0.05, 0.05] if self._lc_plot_is_mag else [0.99, 1.01]
        self._lc_ylim_step = 0.001 if self._lc_plot_is_mag else 0.01

        xx = 1 / (self.targets + 2)
        gs = gridspec.GridSpec(self.targets, 4, self.progress_figure.figure, 0.01, xx, 0.99, 1 - xx, 1.0, 0.1)

        for target in range(self.targets):
            self.axes_fits.append(self.progress_figure.figure.add_subplot(gs[target, 0]))

            circle = mpatches.Circle((0, 0), self.targets_aperture[target], ec='r', fill=False)
            self.axes_fits[-1].add_patch(circle)
            self.circles_fits.append(circle)

            self.images_fits.append(self.axes_fits[-1].imshow(
                0 * self.first_fits_data[0: 2 * self.star_image_lim, 0: 2 * self.star_image_lim],
                origin='lower',
                extent=(- self.star_image_lim, self.star_image_lim, - self.star_image_lim, self.star_image_lim),
                cmap=Greys_r,
                vmin=self.first_fits_header[self.log.mean_key] + self.log.frame_low_std * self.first_fits_header[self.log.std_key],
                vmax=self.first_fits_header[self.log.mean_key] + self.log.frame_upper_std * self.first_fits_header[self.log.std_key]
            ))

            self.axes_fits[-1].axis('off')
            self.axes_fits[-1].set_xlim(- self.star_plot_lim, self.star_plot_lim)
            self.axes_fits[-1].set_ylim(- self.star_plot_lim, self.star_plot_lim)

            self.axes_lc.append(self.progress_figure.figure.add_subplot(gs[target, 1:]))

            self.images_text_lc.append(
                self.axes_lc[-1].text((self.results['jd'][-1] - self.results['jd'][0]) * 24 / 2, 1, ' ', fontsize=10,
                                      va='center', ha='center'))
            self.images_gauss_lc.append(
                self.axes_lc[-1].plot((np.array(self.results['jd']) - self.results['jd'][0]) * 24,
                                      self.results['gauss_flux'][0], 'ro', ms=3, label='PSF'))
            self.images_aperture_lc.append(
                self.axes_lc[-1].plot((np.array(self.results['jd']) - self.results['jd'][0]) * 24,
                                      self.results['aperture_flux'][0], 'ko', ms=3, label='Aperture'))

            self.axes_lc[-1].set_ylim(self.axes_lc_ylims[0], self.axes_lc_ylims[1])
            self.axes_lc[-1].set_xlim(-0.1/60, (max(self.results['jd']) - min(self.results['jd'])) * 24 + 0.1/60)
            if target == 0:
                self.axes_lc[-1].set_ylabel('T', fontsize=12)
            else:
                self.axes_lc[-1].set_ylabel('C{0}'.format(target), fontsize=12)

            if target != self.targets - 1:
                self.axes_lc[-1].tick_params(labelbottom=False, labelsize=8)
            else:
                xl = 'Time (hours in observation)'
                if self._lc_plot_is_mag:
                    xl += ' — Delta m (mag)'
                self.axes_lc[-1].set_xlabel(xl, fontsize=8)
                self.axes_lc[-1].tick_params(labelsize=8)

        self.axes_lc[0].legend(bbox_to_anchor=(1, 2.2), fontsize='x-small')

        if self.targets == 2:
            self.images_text_lc[1].set_text('Can\'t plot relative curve with only 1 active comparison')

        # progress bar and diagnostics

        self.progress_photometry = self.Progressbar(task="Photometry")

        self.target_label = self.Label(text='Target')

        self.progress_diagnostics = [self.target_label]
        self.progress_active = [self.CheckButton(text='', initial=1)]
        self.progress_active[0].disable()
        for target in range(1, self.targets):
            self.progress_diagnostics.append(self.Label(text='Comparison {0}'.format(target)))
            self.progress_active.append(self.CheckButton(text='', initial=1, command=self.replot_results))

        for i in self.progress_active:
            i.disable()

        # buttons

        self.stop_and_return_button = self.Button(
            text='STOP PHOTOMETRY', command=self.trigger_exit)
        self.save_button = self.Button(
            text='SAVE RESULTS', command=self.save)
        self.return_to_photomertry_button = self.Button(
            text='RETURN TO PHOTOMETRY MENU', command=self.close)
        self.proceed_button = self.Button(
            text='PROCEED TO FITTING MENU', command=self.proceed)

        # structure

        structure = [
            [[self.Label(text=' '), 0], [self.Label(text='Active'), 1], [self.progress_figure, 2, 2, self.targets + 2]],
            [[self.progress_diagnostics[0], 0], [self.progress_active[0], 1]],
        ]

        for i in range(1, self.targets):
            structure.append([[self.progress_diagnostics[i], 0], [self.progress_active[i], 1]])

        structure.append([[self.Label(text='...'), 0]])
        structure.append([])

        structure.append([[self.progress_photometry, 2], [self.stop_and_return_button, 3]])
        structure.append([[self.save_button, 0, 2], [self.return_to_photomertry_button, 2], [self.proceed_button, 3]])
        structure.append([])

        self.set_close_button_function(self.trigger_exit)

        self.setup_window(structure, main_font='Courier')

        self.stop_and_return_button.activate()
        self.save_button.disable()
        self.return_to_photomertry_button.disable()
        self.proceed_button.disable()

    def _photometry_mag_domain(self):
        return _log_param_bool_safe(self.log, 'photometry_use_magnitude_domain', False)

    def _lc_indices_all(self):
        return np.arange(self.targets, dtype=int)

    def _lc_indices_active(self):
        return np.array([t for t in range(self.targets) if self.progress_active[t].get()], dtype=int)

    def _denom_flux_ratio_only(self, flux, row, active_idx):
        if len(active_idx) == 0:
            return np.full(flux.shape[1], np.nan)
        if row == 0:
            ids = [i for i in active_idx if i != 0]
            if not ids:
                return np.full(flux.shape[1], np.nan)
            return np.nansum(flux[np.array(ids, dtype=int), :], axis=0)
        left = [i for i in active_idx if 1 <= i < row]
        right = [i for i in active_idx if i >= row]
        if not left and not right:
            return np.full(flux.shape[1], np.nan)
        acc = np.zeros(flux.shape[1], dtype=float)
        if left:
            acc += np.nansum(flux[np.array(left, dtype=int), :], axis=0)
        if right:
            acc += np.nansum(flux[np.array(right, dtype=int), :], axis=0)
        return acc

    def _denom_flux_error_only(self, ferr, row, active_idx):
        if row == 0:
            ids = [i for i in active_idx if i != 0]
            if not ids:
                return np.full(ferr.shape[1], np.nan)
            return np.sqrt(np.nansum(ferr[np.array(ids, dtype=int), :] ** 2, axis=0))
        left = [i for i in active_idx if 1 <= i < row]
        right = [i for i in active_idx if i >= row]
        if not left and not right:
            return np.full(ferr.shape[1], np.nan)
        s2 = np.zeros(ferr.shape[1], dtype=float)
        if left:
            s2 += np.nansum(ferr[np.array(left, dtype=int), :] ** 2, axis=0)
        if right:
            s2 += np.nansum(ferr[np.array(right, dtype=int), :] ** 2, axis=0)
        return np.sqrt(s2)

    def _denom_flux_ratio_replot_comp(self, flux, row, active_idx):
        """Dénominateur des courbes comparaison dans replot : somme des autres comps actives (sans la cible 0)."""
        ids = [i for i in active_idx if i != row and i >= 1]
        if not ids:
            return np.full(flux.shape[1], np.nan)
        return np.nansum(flux[np.array(ids, dtype=int), :], axis=0)

    def _denom_flux_error_replot_comp(self, ferr, row, active_idx):
        ids = [i for i in active_idx if i != row and i >= 1]
        if not ids:
            return np.full(ferr.shape[1], np.nan)
        return np.sqrt(np.nansum(ferr[np.array(ids, dtype=int), :] ** 2, axis=0))

    def _row_lc_values(self, flux, ferr, row, active_idx, force_flux=False, replot_comp=False):
        if replot_comp and row > 0:
            den = self._denom_flux_ratio_replot_comp(flux, row, active_idx)
            sig_d = self._denom_flux_error_replot_comp(ferr, row, active_idx)
        else:
            den = self._denom_flux_ratio_only(flux, row, active_idx)
            sig_d = self._denom_flux_error_only(ferr, row, active_idx)
        num = flux[row, :]
        sig_n = ferr[row, :]
        if self._photometry_mag_domain() and not force_flux:
            slope = effective_transformation_slope(self.log)
            lc, err = delta_mag_from_flux_ratio(num, den, sig_n, sig_d, slope)
            return lc, err, True
        ratio = num / den
        err = np.sqrt(
            (sig_n / np.maximum(np.abs(num), 1e-30)) ** 2 + (sig_d / np.maximum(np.abs(den), 1e-30)) ** 2
        ) * np.abs(ratio)
        return ratio, err, False

    def _normalize_lc_plot(self, lc, err, is_mag):
        if is_mag:
            med = np.nanmedian(lc)
            return lc - med, err
        med = np.nanmedian(lc)
        return lc / med, err

    def run_photometry(self):

        self.log.set_param('proceed', 'return_to_photometry')

        self.science_counter = 0
        self.target_fails = np.zeros(self.targets)
        print('Photometry: start - {0} frame(s), {1} target(s)'.format(len(self.science_files), self.targets))
        self.log.runtime('PhotometryProgress: start - {0} frame(s), {1} target(s)'.format(len(self.science_files), self.targets))

        self.after(self.measure)

    def measure(self):

        if self.exit:
            self.after(self.options)

        else:

            if self.science_counter == 0:
                self.progress_photometry.initiate(len(self.science_files))

            counter = self.science_counter
            science_file = self.science_files[counter]
            self.progress_photometry.show_message(
                'Frame {0}/{1}: {2}'.format(counter + 1, len(self.science_files), science_file)
            )
            if counter % 10 == 0 or counter == len(self.science_files) - 1:
                print('Photometry: processing frame {0}/{1} -> {2}'.format(
                    counter + 1, len(self.science_files), science_file
                ))
                self.log.runtime('PhotometryProgress: frame {0}/{1} -> {2}'.format(
                    counter + 1, len(self.science_files), science_file
                ))

            fits_data, fits_header = get_fits_data_and_header(os.path.join(self.log.reduction_directory, science_file))

            ref_x_position = fits_header[self.log.align_x0_key]
            ref_y_position = fits_header[self.log.align_y0_key]
            ref_u_position = fits_header[self.log.align_u0_key]

            for target in range(self.targets):

                if self.exit:
                    break

                x = (ref_x_position + self.targets_r_position[target] *
                     np.cos(ref_u_position + self.targets_u_position[target]))
                y = (ref_y_position + self.targets_r_position[target] *
                     np.sin(ref_u_position + self.targets_u_position[target]))

                star = image_find_stars(
                    fits_data, fits_header,
                    x_low=x - 3 * fits_header[self.log.psf_key],
                    x_upper=x + 3 * fits_header[self.log.psf_key],
                    y_low=y - 3 * fits_header[self.log.psf_key],
                    y_upper=y + 3 * fits_header[self.log.psf_key],
                    x_centre=x,
                    y_centre=y,
                    mean=fits_header[self.log.mean_key],
                    std=fits_header[self.log.std_key],
                    burn_limit=fits_header[self.log.hops_saturation_key] * self.saturation,
                    psf=fits_header[self.log.psf_key],
                    aperture=self.targets_aperture[target] * self.psf_ratio[counter] / fits_header[self.log.psf_key],
                    sky_inner_aperture=self.sky_inner_aperture, sky_outer_aperture=self.sky_outer_aperture,
                    order_by_flux=False,
                    centroids_snr=self.centroids_snr, stars_snr=self.stars_snr
                )

                if star or self.faint_target_mode:

                    try:

                        if star:
                            star = star[0]

                            x_mean = star[0]
                            y_mean = star[1]
                            norm = star[2]
                            floor = star[3]
                            x_std = star[4]
                            y_std = star[5]
                            total_app_flux = star[6]
                            sky_flux = star[8]
                            sky_flux_unc = star[9]

                        else:

                            x_mean = (ref_x_position + self.targets_r_position[target] *
                                      np.cos(ref_u_position + self.targets_u_position[target]))
                            y_mean = (ref_y_position + self.targets_r_position[target] *
                                      np.sin(ref_u_position + self.targets_u_position[target]))
                            floor = fits_header[self.log.mean_key]
                            x_std = fits_header[self.log.psf_key]
                            y_std = fits_header[self.log.psf_key]
                            total_app_flux = aperture_photometry(fits_data, CircularAperture(np.array([x_mean-0.5, y_mean-0.5]),
                                                                                             self.targets_aperture[target]))['aperture_sum'][0]
                            sky_flux = np.pi * (self.targets_aperture[target]**2) * fits_header[self.log.mean_key]
                            sky_flux_unc = np.sqrt(np.pi * (self.targets_aperture[target]**2)) * fits_header[self.log.std_key]
                            norm = (total_app_flux - sky_flux) / (2 * np.pi * x_std * y_std)

                        # save psf photometry

                        self.results['gauss_x_position'][target][counter] = x_mean
                        self.results['gauss_y_position'][target][counter] = y_mean
                        self.results['gauss_x_std'][target][counter] = x_std
                        self.results['gauss_y_std'][target][counter] = y_std
                        self.results['gauss_flux'][target][counter] = 2 * np.pi * norm * x_std * y_std
                        self.results['gauss_flux_error'][target][counter] = np.sqrt(
                            np.abs(2 * np.pi * norm * x_std * y_std)
                        )

                        if star and self.moving_target_mode:

                            target_polar = cartesian_to_polar(x_mean, y_mean,
                                                              ref_x_position, ref_y_position)

                            self.targets_r_position[target] = target_polar[0]
                            self.targets_u_position[target] = target_polar[1] - ref_u_position


                        if star and self.use_geometric_center:
                            x1 = int(star[0] - 3 * fits_header[self.log.psf_key])
                            x2 = x1 + int(6 * fits_header[self.log.psf_key]) + 1
                            y1 = int(star[1] - 3 * fits_header[self.log.psf_key])
                            y2 = y1 + int(6 * fits_header[self.log.psf_key]) + 1

                            area = fits_data[y1:y2, x1:x2]

                            area_x, area_y = np.meshgrid(
                                np.arange(x1, x2) + 0.5,
                                np.arange(y1, y2) + 0.5)

                            x_mean = np.sum(area * area_x)/np.sum(area)
                            y_mean = np.sum(area * area_y)/np.sum(area)

                            total_app_flux = aperture_photometry(fits_data, CircularAperture(np.array([x_mean-0.5, y_mean-0.5]),
                                                                                             self.targets_aperture[target]))['aperture_sum'][0]

                        # progress plot

                        plot_x_min = int(x_mean - self.star_image_lim)
                        plot_y_min = int(y_mean - self.star_image_lim)

                        self.images_fits[target].set_data(
                            fits_data[plot_y_min: plot_y_min + 2 * self.star_image_lim,
                            plot_x_min: plot_x_min + 2 * self.star_image_lim])
                        self.images_fits[target].set_clim(
                            fits_header[self.log.mean_key] + self.log.frame_low_std * fits_header[
                                self.log.std_key],
                            fits_header[self.log.mean_key] + self.log.frame_upper_std * fits_header[
                                self.log.std_key])
                        self.images_fits[target].set_extent((plot_x_min, plot_x_min + 2 * self.star_image_lim,
                                                             plot_y_min, plot_y_min + 2 * self.star_image_lim))

                        self.axes_fits[target].set_xlim(x_mean - self.star_plot_lim,
                                                        x_mean + self.star_plot_lim)
                        self.axes_fits[target].set_ylim(y_mean - self.star_plot_lim,
                                                        y_mean + self.star_plot_lim)

                        self.circles_fits[target].set_center((x_mean, y_mean))

                        self.circles_fits[target].set_radius(self.targets_aperture[target] * self.psf_ratio[counter])

                        # save aperture photometry

                        self.results['aperture_x_position'][target][counter] = x_mean
                        self.results['aperture_y_position'][target][counter] = y_mean
                        self.results['aperture_background'][target][counter] = sky_flux
                        self.results['aperture_background_error'][target][counter] = sky_flux_unc
                        self.results['aperture_flux'][target][counter] = total_app_flux - sky_flux
                        self.results['aperture_flux_error'][target][counter] = np.sqrt(
                            np.abs(total_app_flux - sky_flux)/self.camera_gain +
                            2 * (sky_flux_unc**2))

                    except Exception as e:
                        print(e)
                        self.log.runtime_exception(
                            'PhotometryProgress: frame {0}/{1}, target {2} failed'.format(
                                counter + 1, len(self.science_files), target
                            ),
                            e
                        )
                        self.target_fails[target] += 1

                else:
                    self.target_fails[target] += 1

                if self.target_fails[target] > 0:
                    if target == 0:
                        name = 'Target'
                    else:
                        name = 'Comparison {0}'.format(target)
                    self.progress_diagnostics[target].set(
                        '{0}\nStar not found\nin {1} frame(s)'.format(name, int(self.target_fails[target])))

            active_all = self._lc_indices_all()

            for target in range(self.targets):

                if self.exit:
                    break

                gauss_raw, gauss_err_raw, g_mag = self._row_lc_values(
                    self.results['gauss_flux'], self.results['gauss_flux_error'], target, active_all
                )
                ap_raw, ap_err_raw, a_mag = self._row_lc_values(
                    self.results['aperture_flux'], self.results['aperture_flux_error'], target, active_all
                )

                gauss_lc, _ = self._normalize_lc_plot(gauss_raw, gauss_err_raw, g_mag)
                aperture_lc, _ = self._normalize_lc_plot(ap_raw, ap_err_raw, a_mag)

                min_data_point = np.nanmin([gauss_lc, aperture_lc])
                max_data_point = np.nanmax([gauss_lc, aperture_lc])

                step = self._lc_ylim_step
                if min_data_point < self.axes_lc_ylims[0]:
                    self.axes_lc_ylims[0] = self.axes_lc_ylims[0] - (
                                int((self.axes_lc_ylims[0] - min_data_point) / step) + 1) * step
                if max_data_point > self.axes_lc_ylims[1]:
                    self.axes_lc_ylims[1] = self.axes_lc_ylims[1] + (
                                int((max_data_point - self.axes_lc_ylims[1]) / step) + 1) * step
                if target == 0 or self.targets > 2:
                    self.images_gauss_lc[target][0].set_ydata(gauss_lc)
                    self.images_aperture_lc[target][0].set_ydata(aperture_lc)

            for ax_lc in self.axes_lc:
                ax_lc.set_ylim(self.axes_lc_ylims[0], self.axes_lc_ylims[1])

            self.progress_figure.draw()
            self.progress_photometry.update()
            self.update_idletasks()
            self.science_counter += 1

            if self.science_counter >= len(self.science_files):
                self.after(self.options)
            else:
                self.after(self.measure)

    def options(self):

        if self.exit:
            self.def_close()
        else:
            self.save()

            if self.targets > 2:
                for i in self.progress_active[1:]:
                    i.activate()

    def replot_results(self):

        active = [True]

        for target in range(1, self.targets):

            if self.progress_active[target].get():
                active.append(True)
                self.images_text_lc[target].set_text(' ')
            else:
                active.append(False)
                self.images_text_lc[target].set_text('Inactive'.format(target))

        active = np.where(active)

        if len(active[0]) == 2:
            for target in range(1, self.targets):
                if self.progress_active[target].get():
                    self.progress_active[target].disable()
                    self.images_text_lc[target].set_text('Can\'t plot relative curve with only 1 active comparison')
        else:
            for target in range(1, self.targets):
                self.progress_active[target].activate()

        self.axes_lc_ylims = [-0.05, 0.05] if self._photometry_mag_domain() else [0.99, 1.01]
        self._lc_ylim_step = 0.001 if self._photometry_mag_domain() else 0.01

        active_idx = self._lc_indices_active()

        for target in range(self.targets):

            if target > 0 and target not in active[0]:
                gauss_lc = self.results['gauss_flux'][target] * np.nan
                aperture_lc = self.results['aperture_flux'][target] * np.nan
            else:
                gauss_raw, gauss_err_raw, g_mag = self._row_lc_values(
                    self.results['gauss_flux'], self.results['gauss_flux_error'], target, active_idx,
                    replot_comp=(target > 0),
                )
                ap_raw, ap_err_raw, a_mag = self._row_lc_values(
                    self.results['aperture_flux'], self.results['aperture_flux_error'], target, active_idx,
                    replot_comp=(target > 0),
                )
                gauss_lc, _ = self._normalize_lc_plot(gauss_raw, gauss_err_raw, g_mag)
                aperture_lc, _ = self._normalize_lc_plot(ap_raw, ap_err_raw, a_mag)

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                min_data_point = np.nanmin([gauss_lc, aperture_lc])
                max_data_point = np.nanmax([gauss_lc, aperture_lc])

                step = self._lc_ylim_step
                if min_data_point < self.axes_lc_ylims[0]:
                    self.axes_lc_ylims[0] = self.axes_lc_ylims[0] - (
                            int((self.axes_lc_ylims[0] - min_data_point) / step) + 1) * step
                if max_data_point > self.axes_lc_ylims[1]:
                    self.axes_lc_ylims[1] = self.axes_lc_ylims[1] + (
                            int((max_data_point - self.axes_lc_ylims[1]) / step) + 1) * step

            self.images_gauss_lc[target][0].set_ydata(gauss_lc)
            self.images_aperture_lc[target][0].set_ydata(aperture_lc)

        for ax_lc in self.axes_lc:
            ax_lc.set_ylim(self.axes_lc_ylims[0], self.axes_lc_ylims[1])

        self.progress_figure.draw()

    def save(self):

        self.stop_and_return_button.disable()
        self.set_close_button_function(self.no_action)
        self.save_button.disable()
        self.return_to_photomertry_button.disable()
        self.proceed_button.disable()
        self.progress_photometry.show_message('Saving results...')
        self.update_idletasks()
        print('Photometry: saving results...')
        self.log.runtime('PhotometryProgress: save started')

        photometry_folders = (glob.glob(os.path.join('{0}*'.format(self.log.photometry_directory_base))))

        def photometry_order(path):
            try:
                return float(path.split('_')[1])
            except:
                return 1

        photometry_directory = '{0}_{1}'.format(
            self.log.photometry_directory_base,
            int(np.max([0] + [photometry_order(ff) for ff in photometry_folders]) + 1)
        )
        os.mkdir(photometry_directory)
        print('Photometry: output directory -> {0}'.format(photometry_directory))
        self.log.runtime('PhotometryProgress: output directory -> {0}'.format(photometry_directory))

        # save fov

        visible_fov_x_min = self.log.get_param('min_x')
        visible_fov_y_min = self.log.get_param('min_y')
        visible_fov_x_max = self.log.get_param('max_x')
        visible_fov_y_max = self.log.get_param('max_y')

        fov = self.FitsWindow(fits_data=self.first_fits_data, fits_header=self.first_fits_header,
                              subplots_adjust=(0.01, 0.99, 0.05, 0.89))

        fov.ax.add_patch(mpatches.Rectangle((visible_fov_x_min + 1, visible_fov_y_min + 1),
                                             visible_fov_x_max - visible_fov_x_min - 2,
                                             visible_fov_y_max - visible_fov_y_min - 2,
                                             ec='r', fill=False))

        for target in range(self.targets):

            if target == 0:
                fov.ax.text(self.targets_x_position[target] + self.targets_aperture[target],
                            self.targets_y_position[target] + self.targets_aperture[target],
                            '$T$({0})'.format(self.targets_aperture[target]), color='r', fontsize=8, va='top', ha='left')
                circle = mpatches.Circle((self.targets_x_position[target], self.targets_y_position[target]),
                                         self.targets_aperture[target],
                                         ec='r', fill=False, label='Target (ap. radius)')
                fov.ax.add_patch(circle)

            else:

                if target == 2:
                    label = 'Comparisons (ap. radius)'
                else:
                    label = None

                if self.progress_active[target].get():
                    fov.ax.text(self.targets_x_position[target] + self.targets_aperture[target],
                                self.targets_y_position[target] + self.targets_aperture[target],
                                '$C_{0}$({1})'.format(target, self.targets_aperture[target]), color='#07fefc', fontsize=8, va='top', ha='left')
                    circle = mpatches.Circle((self.targets_x_position[target], self.targets_y_position[target]),
                                             self.targets_aperture[target],
                                             ec='#07fefc', fill=False, label=label)
                    fov.ax.add_patch(circle)

                else:
                    fov.ax.text(self.targets_x_position[target] + self.targets_aperture[target],
                                self.targets_y_position[target] + self.targets_aperture[target],
                                '$C_{0}$({1}) - Inactive'.format(target, self.targets_aperture[target]), color='#07fefc', fontsize=8, va='top', ha='left')
                    circle = mpatches.Circle((self.targets_x_position[target], self.targets_y_position[target]),
                                             self.targets_aperture[target],
                                             ec='#07fefc', fill=False)
                    fov.ax.add_patch(circle)

        fov.ax.legend(loc=(0, 1.01))

        fov.figure.savefig(os.path.join(photometry_directory, self.log.fov_figure), dpi=200)

        self.progress_figure.figure.savefig(os.path.join(photometry_directory, self.log.lc_figure), dpi=200)
        self.progress_photometry.show_message('Saving lightcurves...')
        self.update_idletasks()

        # save log

        for target in range(1, self.targets):
            self.log.set_param('comparison_{0}_active'.format(target), self.progress_active[target].get())

        # save lightcurves

        active_idx = self._lc_indices_active()

        gauss_lc, gauss_lc_error, _ = self._row_lc_values(
            self.results['gauss_flux'], self.results['gauss_flux_error'], 0, active_idx, force_flux=True
        )
        aperture_lc, aperture_lc_error, _ = self._row_lc_values(
            self.results['aperture_flux'], self.results['aperture_flux_error'], 0, active_idx, force_flux=True
        )

        valid_gauss = np.where(~np.isnan(gauss_lc))
        valid_aperture = np.where(~np.isnan(aperture_lc))

        targets_results = [self.results['file_names'][valid_gauss], self.results['jd'][valid_gauss]]

        for array in ['gauss_x_position', 'gauss_y_position', 'gauss_x_std', 'gauss_y_std', 'gauss_flux',
                      'gauss_flux_error']:
            for target in range(self.targets):
                targets_results.append(self.results[array][target][valid_gauss])

        np.savetxt(os.path.join(photometry_directory, self.log.photometry_file.replace('.txt', '_g.txt')),
                   np.swapaxes(targets_results, 0, 1), fmt="%s")

        np.savetxt(os.path.join(photometry_directory, self.log.light_curve_gauss_file), np.swapaxes([
            self.results['jd'][valid_gauss], gauss_lc[valid_gauss], gauss_lc_error[valid_gauss]
        ], 0, 1))

        targets_results = [self.results['file_names'][valid_aperture], self.results['jd'][valid_aperture]]

        for array in ['aperture_x_position', 'aperture_y_position', 'aperture_flux',
                      'aperture_flux_error', 'aperture_background', 'aperture_background_error']:
            for target in range(self.targets):
                targets_results.append(self.results[array][target][valid_aperture])

        np.savetxt(os.path.join(photometry_directory, self.log.photometry_file.replace('.txt', '_a.txt')),
                   np.swapaxes(targets_results, 0, 1), fmt="%s")

        np.savetxt(os.path.join(photometry_directory, self.log.light_curve_aperture_file), np.swapaxes([
            self.results['jd'][valid_aperture], aperture_lc[valid_aperture], aperture_lc_error[valid_aperture]
        ], 0, 1))

        if self._photometry_mag_domain():
            gauss_dm, gauss_dm_err, _ = self._row_lc_values(
                self.results['gauss_flux'], self.results['gauss_flux_error'], 0, active_idx, force_flux=False
            )
            aperture_dm, aperture_dm_err, _ = self._row_lc_values(
                self.results['aperture_flux'], self.results['aperture_flux_error'], 0, active_idx, force_flux=False
            )
            valid_dm_g = np.where(~np.isnan(gauss_dm))
            valid_dm_a = np.where(~np.isnan(aperture_dm))
            hdr = (
                '# JD_UTC delta_mag mag_sigma ; Delta m = a*(-2.5*log10(F_target/F_den)) '
                '(a=coeff. NPOAP si actif). Fichiers PHOTOMETRY_* sans suffixe = flux relatif pour Ajustement/ExoClock.'
            )
            np.savetxt(
                os.path.join(photometry_directory, 'PHOTOMETRY_GAUSS_MAGDIFF.txt'),
                np.swapaxes(
                    [self.results['jd'][valid_dm_g], gauss_dm[valid_dm_g], gauss_dm_err[valid_dm_g]], 0, 1
                ),
                header=hdr,
            )
            np.savetxt(
                os.path.join(photometry_directory, 'PHOTOMETRY_APERTURE_MAGDIFF.txt'),
                np.swapaxes(
                    [self.results['jd'][valid_dm_a], aperture_dm[valid_dm_a], aperture_dm_err[valid_dm_a]], 0, 1
                ),
                header=hdr,
            )

        # save output description

        shutil.copy(self.log.files['photometry_output_description'], photometry_directory)

        # save exoclock info

        ra_dec_string = self.log.get_param('target_ra_dec')
        ra_dec_string = ra_dec_string.split(' ')
        try:
            # Evite un freeze si le service externe met trop de temps.
            def _locate():
                return exoclock.locate_planet(
                    exoclock.Hours(ra_dec_string[0]),
                    exoclock.Degrees(ra_dec_string[1])
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                fut = executor.submit(_locate)
                planet_obj = fut.result(timeout=8)
            planet = planet_obj.name
        except Exception:
            planet = 'Could not find a planet in the ExoClock catalogue at this location'
            print('Photometry: ExoClock lookup skipped/timeout')

        phot_filter = self.log.get_param('filter')

        flux_format_line = 'Flux format: Flux \n(flux of target over summed flux of comparisons)'
        if self._photometry_mag_domain():
            flux_format_line += (
                '\n\nNPOAP / magnitudes: PHOTOMETRY_*_MAGDIFF.txt donne Delta m = a*(-2.5 log10(F_t/F_den)) '
                'avec le meme denominateur que le rapport de flux ; les termes b des coefficients se neutralisent '
                'pour cette difference. Les fichiers PHOTOMETRY_APERTURE.txt et PHOTOMETRY_GAUSS.txt '
                'restent en flux relatif pour ce menu Ajustement et ExoClock.'
            )

        w = open(os.path.join(photometry_directory, 'ExoClock_info.txt'), 'w')
        w.write('\n'.join([
            'The ExoClock Project is an effort to keep the ephemerides of exoplanets as precise as \n'
            'possible for planning future observations. If you have observed an exoplanet you can\n'
            'contribute your observation at: \n\nhttps://www.exoclock.space\n\n'
            'File to upload: PHOTOMETRY_APERTURE.txt \n(this is a suggestion based on passt experience, '
            'you can also try \nuploading PHOTOMETRY_GAUSS.txt)',
            '',
            'Planet: {0}'.format(planet),
            '',
            'Time format: JD_UTC \n(UTC-based Julian date)',
            '',
            'Time stamp: Exposure start \n(the time produced refers to the beginning of each exposure)',
            '',
            flux_format_line,
            '',
            'Filter: {0}'.format(phot_filter),
            '',
            'Exposure time in seconds: {0}'.format(self.exposure_time),
        ]))
        w.close()

        # saving ok

        self.log.set_param('photometry_complete', True)
        self.log.set_param('photometry_version', self.log.version)

        self.log.save_local_log()

        self.log.export_local_log(photometry_directory)
        self.progress_photometry.show_message('Save completed')
        self.update_idletasks()
        print('Photometry: save completed')
        self.log.runtime('PhotometryProgress: save completed')

        self.showinfo('Results saved successfully',
                      'Your results have been saved successfully in {0}'.format(photometry_directory))
        self.show()

        self.set_close_button_function(self.close)
        self.save_button.activate()
        self.return_to_photomertry_button.activate()
        self.proceed_button.activate()

    def proceed(self):

        self.log.set_param('proceed', True)
        self.close()
