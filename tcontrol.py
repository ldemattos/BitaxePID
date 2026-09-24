#!/usr/bin/env python3
"""
tcontrol Module for BitaxePID Auto-Tuner

Implements `tcontrol`, a temperature-only control strategy that adjusts the
miner's core voltage to hold a target die temperature, as an alternative to
the hashrate-driven `PIDTuningStrategy` in implementations.py. Frequency is
left untouched; only voltage is adjusted.

Block diagram (see specs/tcontrol.docx):

    T setpoint --(+)--> [sum] --> [deadband -deltaT..+deltaT] --> Kp,Ki,Kd (P/I/D) --(+)--> deltaT
                          ^ (-)                                                     |
                          |                                                         v
                     T measured                                    deltaT --(x)--> [combine] <--(1/x)-- T setpoint
                                                                                         |
                                                                         factor = 1 + deltaT/T_setpoint
                                                                                         |
                                                    V_new = clamp(V_setpoint * factor, Vmin, Vmax)
                                                                                         |
                                                                      V_setpoint (next iteration) <-------+

Concretely, each call to `apply_strategy`:
    1. error         = target_temp - measured_temp
    2. error_band     = 0 if -max_delta_t <= error <= +max_delta_t else error
                         # a deadband, not a clamp: inside +-max_delta_t the
                         # PID is fed zero error; outside the band the
                         # *actual* error passes through unaltered (not
                         # shifted or capped). Either way the PID is stepped
                         # the same way every call -- the deadband only
                         # changes what is fed in as u, never what happens
                         # to the output afterward.
    3. delta_t        = PID(error_band)   # Kp, Ki, Kd, via a discretized
                                           # transfer function built with
                                           # the `control` package, stepped
                                           # every call with whatever
                                           # error_band produced
    4. factor         = 1 + delta_t / target_temp
    5. new_voltage    = clip(current_voltage * factor, min_voltage, max_voltage)

`current_voltage` (the previous iteration's voltage setpoint, tracked by
TuningManager and passed into `apply_strategy` on every call) plays the role
of "Vsetpoint" feeding back into itself in the diagram, so no extra internal
voltage state is needed here.

Dependencies:
    - control, numpy
"""

import logging
from typing import Tuple

import numpy as np

try:
    import control
except ImportError as e:  # pragma: no cover - surfaced at import time
    raise ImportError(
        "The 'control' package is required for tcontrol (pip install control). "
        "See requirements.txt."
    ) from e

from interfaces import TuningStrategy


def _build_discrete_pid(
    kp: float, ki: float, kd: float, sample_interval: float, deriv_filter_n: float = 10.0
) -> "control.StateSpace":
    """
    Build a discretized PID compensator using the `control` package.

    C(s) = Kp + Ki/s + Kd*s/(1 + s/N)

    A pure derivative term (Kd*s alone) is an improper transfer function, so
    a first-order filter (deriv_filter_n) is applied to the derivative term
    to keep the compensator proper and realizable, a standard technique for
    implementable PID controllers. The continuous compensator is discretized
    with the Tustin (bilinear) method at `sample_interval` seconds and
    converted to a state-space realization so it can be stepped one sample
    at a time.

    Args:
        kp (float): Proportional gain.
        ki (float): Integral gain.
        kd (float): Derivative gain.
        sample_interval (float): Sample time (seconds), matching the tuning
            loop's SAMPLE_INTERVAL.
        deriv_filter_n (float): Derivative filter coefficient (higher = closer
            to an ideal derivative).

    Returns:
        control.StateSpace: Discrete-time state-space realization of C(z).
    """
    s = control.tf("s")
    c_continuous = kp + ki / s + (kd * s) / (1 + s / deriv_filter_n)
    c_discrete = control.sample_system(c_continuous, sample_interval, method="tustin")
    return control.tf2ss(c_discrete)


class tcontrol(TuningStrategy):
    """
    Temperature-only tuning strategy: holds `target_temp` by adjusting core
    voltage via a PID compensator built with the `control` package. Frequency
    is left unchanged (this strategy never adjusts it).

    An alternative to `PIDTuningStrategy` (implementations.py), selectable at
    runtime with `--control-strategy tcontrol` (or CONTROL_STRATEGY=tcontrol).
    """

    def __init__(
        self,
        kp: float,
        ki: float,
        kd: float,
        sample_interval: float,
        target_temp: float,
        max_delta_t: float,
        min_voltage: float,
        max_voltage: float,
    ) -> None:
        """
        Initialize the temperature control strategy.

        Args:
            kp (float): Proportional gain (TCONTROL_KP).
            ki (float): Integral gain (TCONTROL_KI).
            kd (float): Derivative gain (TCONTROL_KD).
            sample_interval (float): Control loop sample time (seconds).
            target_temp (float): Target die temperature, "T setpoint" (deg C).
            max_delta_t (float): Symmetric deadband applied to the temperature
                error before the PID terms, "+-deltaT" in the block diagram
                (TCONTROL_MAX_DELTA_T, deg C). While the error stays within
                +-max_delta_t, the PID is fed zero error instead of the
                measured error (stepped exactly like any other call, just
                with u=0); outside that band, the actual (unclamped) error
                is fed in. In both cases the PID's output goes on to set
                factor/new_voltage the same way -- the deadband is never
                overridden or discarded afterward, so there is no
                discontinuity at the band edges.
            min_voltage (float): Minimum allowed voltage (mV), "Vmin".
            max_voltage (float): Maximum allowed voltage (mV), "Vmax".
        """
        logging.debug(
            "tcontrol input variables: "
            f"kp={kp} ki={ki} kd={kd} sample_interval={sample_interval} "
            f"target_temp={target_temp} max_delta_t={max_delta_t} "
            f"min_voltage={min_voltage} max_voltage={max_voltage}"
        )
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.sample_interval = sample_interval
        self.target_temp = target_temp
        self.max_delta_t = max_delta_t
        self.min_voltage = min_voltage
        self.max_voltage = max_voltage

        self._sys = _build_discrete_pid(kp, ki, kd, sample_interval)
        self._state = np.zeros((self._sys.nstates, 1))

    def apply_strategy(
        self,
        current_voltage: float,
        current_frequency: float,
        temp: float,
        hashrate: float,
        power: float,
    ) -> Tuple[float, float]:
        """
        Calculate a new voltage setting to drive `temp` toward `target_temp`.
        Frequency is always returned unchanged.

        Args:
            current_voltage (float): Current target voltage setting (mV);
                doubles as "Vsetpoint" fed back into the block diagram.
            current_frequency (float): Current target frequency (MHz),
                returned unchanged.
            temp (float): Measured temperature, "T measured" (deg C).
            hashrate (float): Unused by this strategy (kept for interface
                compatibility with TuningStrategy).
            power (float): Unused by this strategy (kept for interface
                compatibility with TuningStrategy).

        Returns:
            Tuple[float, float]: (new_voltage, current_frequency).
        """
        error = self.target_temp - temp
        # Deadband (not a clamp): inside +-max_delta_t, the PID is fed zero
        # error -- not skipped, not overridden afterward. It is stepped
        # every call exactly like the out-of-band case, just with u=0
        # instead of u=error, so its state evolves continuously and delta_t
        # (and therefore factor/new_voltage) is whatever the PID naturally
        # computes for that input. There is no separate branch that forces
        # factor=1.0 or pins new_voltage to current_voltage: the deadband's
        # only effect is on what is fed into the PID, never on its output.
        in_deadband = -self.max_delta_t <= error <= self.max_delta_t
        error_band = 0.0 if in_deadband else error

        u = np.array([[error_band]])
        y = self._sys.C @ self._state + self._sys.D @ u
        self._state = self._sys.A @ self._state + self._sys.B @ u
        delta_t = float(y[0, 0])

        factor = 1 + delta_t / self.target_temp
        new_voltage_raw = current_voltage * factor
        new_voltage = max(self.min_voltage, min(self.max_voltage, new_voltage_raw))

        logging.info(
            f"tcontrol: measured_temp={temp}C target_temp={self.target_temp}C "
            f"error={error:.3f} error_band={error_band:.3f} in_deadband={in_deadband} "
            f"PID_output(deltaT)={delta_t:.4f} voltage_setpoint={new_voltage:.2f}mV"
        )
        logging.debug(
            f"tcontrol: current_voltage={current_voltage} factor={factor:.6f} "
            f"bounds=[{self.min_voltage},{self.max_voltage}] "
            f"frequency (unchanged)={current_frequency}MHz"
        )

        return new_voltage, current_frequency
