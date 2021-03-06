# -*- coding: utf-8 -*-
"""
Collection of functions that compute stuff using
as input data produced with the classical psha method.
"""

import math
import numpy

from scipy.interpolate import interp1d # pylint: disable=E1101, E0611
from scipy.stats.mstats import mquantiles

from openquake import kvs
from openquake import shapes
from openquake.logs import LOG


QUANTILE_PARAM_NAME = "QUANTILE_LEVELS"
POES_PARAM_NAME = "POES_HAZARD_MAPS"


def compute_mean_curve(curves):
    """Compute a mean hazard curve.
    
    The input parameter is a list of arrays where each array
    contains just the y values of the corresponding hazard curve.
    """
    return numpy.array(curves).mean(axis=0)


def compute_quantile_curve(curves, quantile):
    """Compute a quantile hazard curve.

    The input parameter is a list of arrays where each array
    contains just the y values of the corresponding hazard curve.
    """
    result = []

    if len(numpy.array(curves).flat):
        result = mquantiles(curves, quantile, axis=0)[0]
    
    return result


def _extract_y_values_from(curve):
    """Extract from a serialized hazard curve (in json format)
    the y values (PoEs) used to compute the mean hazard curve.
    
    The serialized hazard curve has this format:
    {"site_lon": 1.0, "site_lat": 1.0, "curve": [{"x": 0.1, "y": 0.2}, ...]}
    """
    y_values = []

    for point in curve:
        y_values.append(float(point["y"]))
        
    return y_values

def _reconstruct_curve_list_from(curve_array):
    """Reconstruct the x,y hazard curve list from numpy array, and leave
    out the un-needed x value."""
    
    return [{'y': poe} for poe in curve_array]

def _acceptable(value):
    """Return true if the value taken from the configuration
    file is valid, false otherwise."""
    try:
        value = float(value)
        return value >= 0.0 and value <= 1.0

    except ValueError:
        return False


def curves_at(job_id, site):
    """Return all the json deserialized hazard curves for
    a single site (different realizations)."""
    pattern = "%s*%s*%s*%s" % (kvs.tokens.HAZARD_CURVE_KEY_TOKEN,
            job_id, site.longitude, site.latitude)

    curves = []
    raw_curves = kvs.mget_decoded(pattern)

    for raw_curve in raw_curves:
        curves.append(_extract_y_values_from(raw_curve["curve"]))
    
    return curves

def hazard_curve_keys_for_job(job_id, sites, 
                              hc_token=kvs.tokens.HAZARD_CURVE_KEY_TOKEN):
    """Return the KVS keys of hazard curves for a given job_id
    and for a given list of sites.
    """

    kvs_keys = []
    for site in sites:
        pattern = "%s*%s*%s*%s" % (hc_token, job_id, site.longitude, 
                                   site.latitude)
        curr_keys = kvs.get_keys(pattern)
        if curr_keys is not None and len(curr_keys) > 0:
            kvs_keys.extend(curr_keys)
    
    return kvs_keys

def mean_hazard_curve_keys_for_job(job_id, sites):
    """Return the KVS keys of mean hazard curves for a given job_id
    and for a given list of sites.
    """
    return hazard_curve_keys_for_job(job_id, sites, 
        kvs.tokens.MEAN_HAZARD_CURVE_KEY_TOKEN)
    
def quantile_hazard_curve_keys_for_job(job_id, sites):
    """Return the KVS keys of quantile hazard curves for a given job_id
    and for a given list of sites.
    """
    return hazard_curve_keys_for_job(job_id, sites, 
        kvs.tokens.QUANTILE_HAZARD_CURVE_KEY_TOKEN)

def _extract_values_from_config(job, param_name):
    """Extract the set of valid values from the configuration file."""
    values = []

    if job.has(param_name):
        raw_values = job.params[param_name].split()
        values = [float(x) for x in raw_values if _acceptable(x)]

    return values


def compute_mean_hazard_curves(job_id, sites):
    """Compute a mean hazard curve for each site in the list
    using as input all the pre-computed curves for different realizations."""

    keys = []
    for site in sites:
        mean_curve = {"site_lon": site.longitude, "site_lat": site.latitude,
            "curve": _reconstruct_curve_list_from(compute_mean_curve(
            curves_at(job_id, site)))}

        key = kvs.tokens.mean_hazard_curve_key(job_id, site)
        keys.append(key)

        kvs.set_value_json_encoded(key, mean_curve)

    return keys


def compute_quantile_hazard_curves(job, sites):
    """Compute a quantile hazard curve for each site in the list
    using as input all the pre-computed curves for different realizations.
    
    The QUANTILE_LEVELS parameter in the configuration file specifies
    all the values used in the computation.
    """

    keys = []
    quantiles = _extract_values_from_config(job, QUANTILE_PARAM_NAME)

    LOG.debug("[QUANTILE_HAZARD_CURVES] List of quantiles is %s" % quantiles)

    for site in sites:
        for quantile in quantiles:

            quantile_curve = {"site_lat": site.latitude,
                "site_lon": site.longitude, 
                "curve": _reconstruct_curve_list_from(compute_quantile_curve(
                curves_at(job.id, site), quantile))}

            key = kvs.tokens.quantile_hazard_curve_key(
                    job.id, site, quantile)
            keys.append(key)

            kvs.set_value_json_encoded(key, quantile_curve)

    return keys


def _extract_imls_from_config(job):
    """Return the list of IMLs defined in the configuration file."""
    return [float(x) for x in job.params[
            "INTENSITY_MEASURE_LEVELS"].split(",")]


def _get_iml_from(curve, job, poe):
    """Return the interpolated IML using the values defined in
    the INTENSITY_MEASURE_LEVELS parameter as the reference grid to
    interpolate in.
    
    IML from config is in ascending order (abscissa of hazard curve)
    PoE from curve is in descending order (ordinate of hazard curve)

    In our interpolation, PoE becomes the x axis, IML the y axis, therefore
    the arrays have to be reversed (x axis has to be monotonically 
    increasing).
    """

    # reverse arrays
    poes = numpy.array(_extract_y_values_from(curve["curve"]))[::-1]
    imls = numpy.log(numpy.array(_extract_imls_from_config(job))[::-1])

    site = shapes.Site(curve["site_lon"], curve["site_lat"])

    if poe > poes[-1]:
        LOG.debug("[HAZARD_MAP] Interpolation out of bounds for PoE %s, "\
            "using maximum PoE value pair, PoE: %s, IML: %s, at site %s" % (
            poe, poes[-1], math.exp(imls[-1]), site))
        return math.exp(imls[-1])

    if poe < poes[0]:
        LOG.debug("[HAZARD_MAP] Interpolation out of bounds for PoE %s, "\
            "using minimum PoE value pair, PoE: %s, IML: %s, at site %s" % (
            poe, poes[0], math.exp(imls[0]), site))
        return math.exp(imls[0])

    return math.exp(interp1d(poes, imls, kind='linear')(poe))

def _store_iml_for(curve, key, job, poe):
    """Store an interpolated IML in kvs along with all
    the needed metadata."""

    im_level = {}

    im_level["site_lon"] = curve["site_lon"]
    im_level["site_lat"] = curve["site_lat"]
    im_level["vs30"] = float(job.params["REFERENCE_VS30_VALUE"])
    im_level["IML"] = _get_iml_from(curve, job, poe)

    kvs.set_value_json_encoded(key, im_level)


def compute_quantile_hazard_maps(job):
    """Compute quantile hazard maps using as input all the
    pre computed quantile hazard curves.

    The POES_HAZARD_MAPS parameter in the configuration file specifies
    all the values used in the computation.
    """

    quantiles = _extract_values_from_config(job, QUANTILE_PARAM_NAME)
    poes = _extract_values_from_config(job, POES_PARAM_NAME)

    LOG.debug("[QUANTILE_HAZARD_MAPS] List of POEs is %s" % poes)
    LOG.debug("[QUANTILE_HAZARD_MAPS] List of quantiles is %s" % quantiles)

    keys = []
    for quantile in quantiles:
        # get all the pre computed quantile curves
        pattern = "%s*%s*%s" % (kvs.tokens.QUANTILE_HAZARD_CURVE_KEY_TOKEN,
                job.id, quantile)

        quantile_curves = kvs.mget_decoded(pattern)

        LOG.debug("[QUANTILE_HAZARD_MAPS] Found %s pre computed " \
                "quantile curves for quantile %s"
                % (len(quantile_curves), quantile))

        for poe in poes:
            for quantile_curve in quantile_curves:
                site = shapes.Site(quantile_curve["site_lon"],
                                   quantile_curve["site_lat"])

                key = kvs.tokens.quantile_hazard_map_key(
                        job.id, site, poe, quantile)
                keys.append(key)

                _store_iml_for(quantile_curve, key, job, poe)
                
    return keys


def compute_mean_hazard_maps(job):
    """Compute mean hazard maps using as input all the
    pre computed mean hazard curves.
    
    The POES_HAZARD_MAPS parameter in the configuration file specifies
    all the values used in the computation.
    """

    poes = _extract_values_from_config(job, POES_PARAM_NAME)

    LOG.debug("[MEAN_HAZARD_MAPS] List of POEs is %s" % poes)

    # get all the pre computed mean curves
    pattern = "%s*%s*" % (kvs.tokens.MEAN_HAZARD_CURVE_KEY_TOKEN, job.id)
    mean_curves = kvs.mget_decoded(pattern)

    LOG.debug("[MEAN_HAZARD_MAPS] Found %s pre computed mean curves"
            % len(mean_curves))

    keys = []
    for poe in poes:
        for mean_curve in mean_curves:
            site = shapes.Site(mean_curve["site_lon"],
                               mean_curve["site_lat"])

            key = kvs.tokens.mean_hazard_map_key(
                    job.id, site, poe)
            keys.append(key)

            _store_iml_for(mean_curve, key, job, poe)
            
    return keys
