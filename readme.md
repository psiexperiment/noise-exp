# Noise exposure

## Introduction

This provides basic noise-exposure functionality for hearing loss experiments.

This package nominally supports both National Instruments and TDT hardware.
Those using National Instruments hardware will have to do some setup work to
map the appropriate inputs and outputs as well as ensure that all devices are
running off of the same sample clock (to ensure precise timing).

For TDT hardware, only the RZ6 is currently supported. Fortunately, the RZ6 is a fairly standard piece of hardware and should be plug-and-play out of the box.

## Installing

Install your preferred Python distribution. For use with National Instruments hardware:

    pip install noise-exp[ni]

For use with TDT hardware:

    pip install noise-exp[tdt]

For use with a sound card:

    pip install noise-exp[soundcard]

## Configuring

The cohort is entered by clicking the cohort button in the launcher, which
opens one field per slot in the exposure cage. Six slots are offered by
default. If your cage holds a different number of animals, set:

    NOISE_EXP_MAX_ANIMALS=4

The microphone and speaker each take a calibration picked in the launcher,
as in the cfts and abts launchers: one on file in cftscal, or a nominal
sensitivity (mV/Pa for the microphone, dB SPL at 1 Vrms for the speaker) when
none has been measured, or unity for the microphone.

Video of the exposure is recorded with psivideo when "Record" is ticked next
to Video in the launcher (the default). The exposure then waits for psivideo
to be running. Untick it to run where there is no camera; set
`NOISE_EXP_RECORD_VIDEO=false` (or use File > Set Defaults) to make that the
default on a machine.

## Exposure level

The noise is scaled so that its level through the speaker calibration is the
level asked for. Exposures run before November 2026 scaled it differently
(see `legacy_level` in psiaudio's `BandlimitedFIRNoiseFactory`), which
usually missed the level by several dB. To repeat one of those exposures
exactly, set "legacy level scaling" to "yes" in the Exposure settings in the
experiment window. It is saved with the data, like the other settings.
