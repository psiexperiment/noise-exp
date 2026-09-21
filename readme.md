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
