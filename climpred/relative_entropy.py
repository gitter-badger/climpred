from collections import OrderedDict

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr
from eofs.xarray import Eof

from climpred.prediction import _pseudo_ens


def _relative_entropy_formula(sigma_b, sigma_x, mu_x, mu_b, neofs):
    """
    Computes the relative entropy formula given in Branstator and Teng, (2010).

    References:
        - Branstator, Grant, and Haiyan Teng. “Two Limits of Initial-Value
            Decadal Predictability in a CGCM.” Journal of Climate 23, no. 23
            (August 27, 2010): 6292–6311. https://doi.org/10/bwq92h.
        - Kleeman, Richard. “Measuring Dynamical Prediction Utility Using
            Relative Entropy.” Journal of the Atmospheric Sciences 59, no. 13
            (July 1, 2002): 2057–72. https://doi.org/10/fqwxpk.

    Args:
        sigma_b (xr.DataArray): covariance matrix of baseline distribution
        sigma_x (xr.DataArray): covariance matrix of forecast distribution
        mu_b (xr.DataArray): mean state vector of the baseline distribution
        mu_x (xr.DataArray): mean state vector of the forecast distribution
        neofs (int): number of EOFs to use

    Returns:
        R (float): relative entropy
        dispersion (float): dispersion component
        signal (float): signal component
    """
    fac = 0.5
    dispersion = fac * (np.log(np.linalg.det(sigma_b) / np.linalg.det(sigma_x))
                        + np.trace(sigma_x / sigma_b) - neofs)

    # https://stackoverflow.com/questions/7160162/left-matrix-division-and-numpy-solve
    # (A.T\B)*A
    x, resid, rank, s = np.linalg.lstsq(
        sigma_b, mu_x - mu_b)  # sigma_b \ (mu_x - mu_b)
    signal = fac * np.matmul((mu_x - mu_b), x)
    R = dispersion + signal
    return R, dispersion, signal


def _gen_control_distribution(ds, control, it=10):
    """
    Generate a large control distribution from control.

    Args:
        ds (xr.DataArray): initialization data with dimensions initialization,
                           member, time, lon (x), lat(y).
        control (xr.DataArray): control data with dimensions time, lon (x),
                                lat(y).
        it (int): multiplying factor for ds.member.

    Returns:
        control_uninitialized (xr.DataArray): data with dimensions
                                              initialization, member, time, lon
                                              (x), lat(y).

    """
    ds_list = []
    for _ in range(it):
        control_uninitialized = _pseudo_ens(ds, control)
        control_uninitialized['initialization'] = ds.initialization.values
        ds_list.append(control_uninitialized)
    control_uninitialized = xr.concat(ds_list, 'member')
    control_uninitialized['member'] =
        np.arange(control_uninitialized.member.size)
    return control_uninitialized


def compute_relative_entropy(initialized, control_uninitialized,
                             anomaly_data=False, neofs=None, curv=True,
                             ntime=None):
    """
    Compute relative entropy.

    Calculates EOFs from anomalies. Projects fields on EOFs to receive
    pseudo-Principle Components per initialization and lead year. Calculate
    relative entropy based on _relative_entropy_formula.

    Args:
        initialized (xr.DataArray): anomaly ensemble data with dimensions
                                    initialization, member, time, lon (x),
                                    lat(y).
        control_uninitialized (xr.DataArray): anomaly control distribution with
                                              dimensions, initialization,
                                              member, time, lon (x), lat(y).
        anomaly_data (bool): Input data is anomaly alread. Default: False.
        neofs (int): number of EOFs to use. Default: initialized.member.size.
        curv (bool): if curvilinear grids are provided disables EOF weights.
        ntime (int): number of timesteps calculated.

    Returns:
        rel_ent (pd.DataFrame): relative entropy

    """
    if neofs is None:
        neofs = initialized.member.size
    if ntime is None:
        ntime = initialized.time.size

    if not anomaly_data:  # if ds, control are raw values
        if detrend_by_control_time_mean:
        anom_x = initialized - control_uninitialized.mean('time')
        anom_b = control_uninitialized - control_uninitialized.mean('time')
    else:  # leave as is when already anomalies
        anom_x = initialized
        anom_b = control_uninitialized

    initializations = initialized.initialization.values
    length = initialized.time.size
    iterables = [['R', 'S', 'D'], initializations]
    mindex = pd.MultiIndex.from_product(
        iterables, names=['component', 'initialization'])
    tt = np.arange(1, length)
    rel_ent = pd.DataFrame(index=tt, columns=mindex)
    rel_ent.index.name = 'Lead Year'
    if curv:  # if curvilinear lon(x,y), lat(x,y) data inputs
        wgts = None
    else:
        coslat = np.cos(np.deg2rad(anom_x.coords['lat'].values))
        wgts = np.sqrt(coslat)[..., np.newaxis]
    base_to_calc_eofs = control_uninitialized.stack(
            new=('member','initialization')).rename({'new'";time"})
    solver = Eof(base_to_calc_eofs, weights=wgts)

    for init in initializations:
        for t in initialized.time.values[:ntime]:
            # P_b base distribution
            pc_b = solver.projectField(anom_b.sel(initialization=init, time=t)
                                             .drop('time')
                                             .rename({'member': 'time'}),
                                       neofs=neofs, eofscaling=0, weighted=False)

            mu_b = pc_b.mean('time')
            sigma_b = xr.DataArray(np.cov(pc_b.T))

            # P_x initialization distribution
            pc_x = solver.projectField(anom_x.sel(initialization=init, time=t)
                                             .drop('time')
                                             .rename({'member': 'time'}),
                                       neofs=neofs, eofscaling=0, weighted=False)

            mu_x = pc_x.mean('time')
            sigma_x = xr.DataArray(np.cov(pc_x.T))

            r, d, s = _relative_entropy_formula(sigma_b, sigma_x, mu_x, mu_b,
                                                neofs)

            rel_ent.T.loc['R', ens][t] = r
            rel_ent.T.loc['D', ens][t] = d
            rel_ent.T.loc['S', ens][t] = s
    return rel_ent


def bootstrap_relative_entropy(initialized, control_uninitialized, sig=95,
                               bootstrap=100, curv=True, neofs=None,
                               ntime=None):
    """
    Bootstrap relative entropy threshold.

    Generates a random uninitialized initialization and calculates the relative
    entropy. sig-th percentile determines threshold level.

    Args:
        initialized (xr.DataArray): initialized ensemble with dimensions
                                    initialization, member, time, lon (x),
                                    lat(y).
        control_uninitialized (xr.DataArray): control distribution with
                                              dimensions initialization,
                                              member, time, lon (x), lat(y).
        sig (int): significance level for threshold.
        bootstrap (int): number of bootstrapping iterations.
        neofs (int): number of EOFs to use. Default: initialized.member.size
        ntime (int): number of timestep to calculate.
                     Default: initialized.time.size.
        curv (bool): if curvilinear grids are provided disables EOF weights.

    Returns:
        rel_ent (pd.DataFrame): relative entropy sig-th percentile threshold.

    """
    if neofs is None:
        neofs = initialized.member.size
    if ntime is None:
        ntime = initialized.time.size

    x = []
    for _ in range(min(1, int(bootstrap / initialized.time.size))):
        ds_control = _pseudo_ens(initialized, control)
        ds_control['initialization'] = initialized.initialization.values
        ds_control['member'] = np.arange(ds_control.member.size)
        ds_pseudo_rel_ent = compute_relative_entropy(
            ds_control, control_uninitialized, neofs=neofs, curv=curv,
            ntime=ntime)
        x.append(ds_pseudo_rel_ent)
    ds_pseudo_metric = pd.concat(x, ignore_index=True)
    qsig = sig / 100
    sig_level = ds_pseudo_metric.stack().apply(lambda g: np.quantile(g, q=qsig))
    return sig_level


def plot_relative_entropy(rel_ent, rel_ent_threshold=None, **kwargs):
    """
    Plot relative entropy results.

    Args:
        rel_ent (pd.DataFrame): relative entropy from compute_relative_entropy
        rel_ent_threshold (pd.DataFrame): threshold from
                                          bootstrap_relative_entropy

    """
    colors = ['royalblue', 'indianred', 'goldenrod']
    fig, ax = plt.subplots(ncols=3, **kwargs)
    for i, dim in enumerate(['R', 'S', 'D']):
        m = rel_ent[dim].median(axis=1)
        std = rel_ent[dim].std(axis=1)
        ax[i].plot(rel_ent[dim], c='gray',
                   label='individual initializations', linewidth=.5, alpha=.5)
        ax[i].plot(m, c=colors[i], label=dim, linewidth=2.5)
        ax[i].plot((m - std), c=colors[i], label=dim + ' median +/- std',
                   linewidth=2.5, ls='--')
        ax[i].plot((m + std), c=colors[i], label='', linewidth=2.5, ls='--')
        if rel_ent_threshold is not None:
            ax[i].axhline(y=rel_ent_threshold[dim],
                          label='bootstrapped threshold', c='gray', ls='--')
        handles, labels = ax[i].get_legend_handles_labels()
        by_label = OrderedDict(zip(labels, handles))
        ax[i].legend(by_label.values(), by_label.keys(), frameon=False)
    ax[0].set_title('Relative Entropy')
    ax[1].set_title('Signal')
    ax[2].set_title('Dispersion')
    ax[0].set_ylim(bottom=0)