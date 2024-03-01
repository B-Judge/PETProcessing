"""Collection of functions to perform graphical analysis on tissue activity curves (TACs).

TODO:
    * Check if it makes more sense to lift out the more mathy methods out into a separate module.
    * Might have to change the division of the TACS cumulative integral by the TACS to be from ``[t_thresh:]`` to
      avoid division by zero.
"""

__version__ = '0.2'

import numba
import numpy as np
from typing import Callable
import os

@numba.njit()
def _line_fitting_make_rhs_matrix_from_xdata(xdata: np.ndarray) -> np.ndarray:
    """Generates the RHS matrix for linear least squares fitting

    Args:
        xdata (np.ndarray): array of independent variable values

    Returns:
        np.ndarray: 2D matrix where first column is `xdata` and the second column is 1s.
        
    """
    out_matrix = np.ones((len(xdata), 2), float)
    out_matrix[:, 0] = xdata
    return out_matrix

@numba.njit()
def fit_line_to_data_using_lls(xdata: np.ndarray, ydata: np.ndarray) -> np.ndarray:
    """Find the linear least squares solution given the x and y variables.
    
    Performs a linear least squares fit to the provided data. Explicitly calls numpy's ``linalg.lstsq`` method by
    constructing the matrix equations. We assume that ``xdata`` and ``ydata`` have the same number of elements.
    
    Args:
        xdata: Array of independent variable values
        ydata: Array of dependent variable values

    Returns:
       Linear least squares solution. (m, b) values
       
    """
    make_2d_matrix = _line_fitting_make_rhs_matrix_from_xdata
    matrix = make_2d_matrix(xdata)
    fit_ans = np.linalg.lstsq(matrix, ydata)[0]
    return fit_ans


@numba.njit()
def cumulative_trapezoidal_integral(xdata: np.ndarray, ydata: np.ndarray, initial: float = 0.0) -> np.ndarray:
    """Calculates the cumulative integral of `ydata` over `xdata` using the trapezoidal rule.
    
    This function is based `heavily` on the ``scipy.integrate.cumtrapz`` implementation.
    `source <https://github.com/scipy/scipy/blob/v0.18.1/scipy/integrate/quadrature.py#L206>`_.
    This implementation only works for 1D arrays and was implemented to work with ``numba``.
    
    Args:
        xdata (np.ndarray): Array for the integration coordinate.
        ydata (np.ndarray): Array for the values to integrate

    Returns:
        np.ndarray: Cumulative integral of ``ydata`` over ``xdata``
    """
    dx = np.diff(xdata)
    cum_int = np.zeros(len(xdata))
    cum_int[0] = initial
    cum_int[1:] = np.cumsum(dx * (ydata[1:] + ydata[:-1]) / 2.0)
    
    return cum_int

# TODO: Add references for the TCMs and Patlak. Could maybe rely on Turku PET Center.
# TODO: Handle cases when tac_vals = 0.0. Might be able to use t_thresh so that we are past the 0-values.
@numba.njit()
def calculate_patlak_x(tac_times: np.ndarray, tac_vals: np.ndarray) -> np.ndarray:
    r"""Calculates the x-variable in Patlak analysis (:math:`\frac{\int_{0}^{T}f(t)\mathrm{d}t}{f(T)}`).
    
    Patlak-Gjedde analysis is a linearization of the 2-TCM with irreversible uptake in the second compartment.
    Therefore, we essentially have to fit a line to some data :math:`y = mx+b`. This function calculates the :math:`x`
    variable for Patlak analysis where,
    .. math::
        x = \frac{\int_{0}_{T} C_\mathrm{P}(t) \mathrm{d}t}{C_\mathrm{P}(t)},
    
    where further :math:`C_\mathrm{P}` is usually the plasma TAC.
    
    Args:
        tac_times (np.ndarray): Array containing the sampled times.
        tac_vals (np.ndarray): Array for activity values at the sampled times.

    Returns:
        np.ndarray: Patlak x-variable. Cumulative integral of activity divided by activity.
    """
    cumulative_integral = cumulative_trapezoidal_integral(xdata=tac_times, ydata=tac_vals, initial=0.0)
    
    return cumulative_integral / tac_vals


@numba.njit()
def get_index_from_threshold(times_in_minutes: np.ndarray, t_thresh_in_minutes: float) -> int:
    """Get the index after which all times are greater than the threshold.

    Args:
        times_in_minutes (np.ndarray): Array containing times in minutes.
        t_thresh_in_minutes (float): Threshold time in minutes.

    Returns:
        int: Index for first time greater than or equal to the threshold time.
        
    Notes:
        If the threshold value is larger than the array, we return -1.
    """
    if t_thresh_in_minutes > np.max(times_in_minutes):
        return -1
    else:
        return np.argwhere(times_in_minutes >= t_thresh_in_minutes)[0, 0]


# TODO: Add more detailed documentation.
@numba.njit()
def patlak_analysis(input_tac_values: np.ndarray,
                    region_tac_values: np.ndarray,
                    tac_times_in_minutes: np.ndarray,
                    t_thresh_in_minutes: float) -> np.ndarray:
    """Performs Patlak-Gjedde analysis given the input TAC, region TAC, times and threshold.
    
    Args:
        input_tac_values (np.ndarray): Array of input TAC values
        region_tac_values (np.ndarray): Array of ROI TAC values
        tac_times_in_minutes (np.ndarray): Array of times in minutes.
        t_thresh_in_minutes (np.ndarray): Threshold time in minutes. Line is fit for all values after the threshold.

    Returns:
        np.ndarray: Array containing :math:`(K_{1}, V_{0})` values.
    
    Notes:
        * We assume that the input TAC and ROI TAC values are sampled at the same times.
    
    """
    t_thresh = get_index_from_threshold(times_in_minutes=tac_times_in_minutes, t_thresh_in_minutes=t_thresh_in_minutes)
    
    patlak_x = calculate_patlak_x(tac_times=tac_times_in_minutes, tac_vals=input_tac_values)
    patlak_y = region_tac_values / input_tac_values
    
    patlak_values = fit_line_to_data_using_lls(xdata=patlak_x[t_thresh:], ydata=patlak_y[t_thresh:])
    
    return patlak_values


@numba.njit()
def logan_analysis(input_tac_values: np.ndarray,
                   region_tac_values: np.ndarray,
                   tac_times_in_minutes: np.ndarray,
                   t_thresh_in_minutes: float) -> np.ndarray:
    """Performs Logan analysis on given input TAC, regional TAC, times and threshold.
    
    Args:
        input_tac_values (np.ndarray): Array of input TAC values
        region_tac_values (np.ndarray): Array of ROI TAC values
        tac_times_in_minutes (np.ndarray): Array of times in minutes.
        t_thresh_in_minutes (np.ndarray): Threshold time in minutes. Line is fit for all values after the threshold.

    Returns:
        np.ndarray: :math:`(V_{d}, \mathrm{Int})`.
        
    Notes:
        * The interpretation of the values depends on the underlying kinetic model.
        * We assume that the input TAC and ROI TAC values are sampled at the same times.
    """
    
    t_thresh = get_index_from_threshold(times_in_minutes=tac_times_in_minutes, t_thresh_in_minutes=t_thresh_in_minutes)
    
    logan_x = cumulative_trapezoidal_integral(xdata=tac_times_in_minutes, ydata=input_tac_values) / region_tac_values
    logan_y = cumulative_trapezoidal_integral(xdata=tac_times_in_minutes, ydata=region_tac_values) / region_tac_values
    
    logan_values = fit_line_to_data_using_lls(xdata=logan_x[t_thresh:], ydata=logan_y[t_thresh:])
    
    return logan_values


@numba.njit()
def alternative_logan_analysis(input_tac_values: np.ndarray,
                               region_tac_values: np.ndarray,
                               tac_times_in_minutes: np.ndarray,
                               t_thresh_in_minutes: float) -> np.ndarray:
    """Performs alternative logan analysis on given input TAC, regional TAC, times and threshold.

    Args:
        input_tac_values (np.ndarray): Array of input TAC values
        region_tac_values (np.ndarray): Array of ROI TAC values
        tac_times_in_minutes (np.ndarray): Array of times in minutes.
        t_thresh_in_minutes (np.ndarray): Threshold time in minutes. Line is fit for all values after the threshold.

    Returns:
        np.ndarray: :math:`(V_{d}, \mathrm{Int})`.

    Notes:
        * The interpretation of the values depends on the underlying kinetic model.
        * We assume that the input TAC and ROI TAC values are sampled at the same times.
    """
    
    t_thresh = get_index_from_threshold(times_in_minutes=tac_times_in_minutes, t_thresh_in_minutes=t_thresh_in_minutes)
    
    alt_logan_x = cumulative_trapezoidal_integral(xdata=tac_times_in_minutes, ydata=input_tac_values) / region_tac_values
    alt_logan_y = cumulative_trapezoidal_integral(xdata=tac_times_in_minutes, ydata=region_tac_values) / input_tac_values
    
    alt_logan_values = fit_line_to_data_using_lls(xdata=alt_logan_x[t_thresh:], ydata=alt_logan_y[t_thresh:])
    
    return alt_logan_values


def get_graphical_analysis_method(method_name: str) -> Callable:
    """
    Function for obtaining the appropriate graphical analysis method.

    This function accepts a string specifying a graphical time-activity curve (TAC) analysis method. It returns a
    reference to the function that performs the selected analysis method.

    Args:
        method_name (str): The name of the graphical method. This should be one of the following strings: 'patlak',
        'logan', or 'alt_logan'.

    Returns:
        function: A reference to the function that performs the corresponding graphical TAC analysis. The returned
        function will take arguments specific to the analysis method, such as input TAC values, tissue TAC values, TAC
        times in minutes, and threshold time in minutes.
    
    Raises:
        ValueError: If `method_name` is not one of the supported graphical analysis methods, i.e., 'patlak', 'logan', or
         'alt_logan'.
    
    Example:
        
        selected_func = get_graphical_analysis_method('logan')
        results = selected_func(input_tac_values, tissue_tac_values,
        tac_times_in_minutes, t_thresh_in_minutes)
    """
    if method_name == "patlak":
        return patlak_analysis
    elif method_name == "logan":
        return logan_analysis
    elif method_name == "alt_logan":
        return alternative_logan_analysis
    else:
        raise ValueError(f"Invalid method_name! Must be either 'patlak', 'logan', or 'alt_logan'. Got {method_name}")
    
class GraphicalAnalysis:
    def __init__(self,
                 input_tac_path: str,
                 roi_tac_path: str,
                 output_directory: str,
                 output_filename_prefix: str) -> None:
        self.input_tac_path = os.path.abspath(input_tac_path)
        self.roi_tac_path = os.path.abspath(roi_tac_path)
        self.output_directory = os.path.abspath(output_directory)
        self.output_filename_prefix = output_filename_prefix
        self.analysis_props = self.init_analysis_props()
        
    def init_analysis_props(self) -> dict:
        props = {'FilePathPTAC': self.input_tac_path,
                 'FilePathTTAC': self.roi_tac_path,
                 'MethodName': None,
                 'ThresholdTime': None,
                 'StartFrameTime': None,
                 'EndFrameTime': None,
                 'NumberOfPointsFit': None}
        return props
    def run_analysis(self, method_name: str, t_thresh_in_minutes: float):
        self.analysis_props['MethodName'] = method_name
        self.analysis_props['ThresholdTime'] = t_thresh_in_minutes
        