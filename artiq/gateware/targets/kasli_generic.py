#!/usr/bin/env python3

import argparse
import json

from misoc.integration.builder import builder_args, builder_argdict
from misoc.targets.kasli import soc_kasli_args, soc_kasli_argdict

from artiq.gateware import rtio
from artiq.gateware.rtio.phy import ttl_simple, ttl_serdes_7series, edge_counter
from artiq.gateware import eem
from artiq.gateware.targets.kasli import StandaloneBase, MasterBase, SatelliteBase
from artiq.build_soc import *


def peripheral_dio(module, peripheral):
    ttl_classes = {
        "input": ttl_serdes_7series.InOut_8X,
        "output": ttl_serdes_7series.Output_8X
    }
    if len(peripheral["ports"]) != 1:
        raise ValueError("wrong number of ports")
    eem.DIO.add_std(module, peripheral["ports"][0],
        ttl_classes[peripheral["bank_direction_low"]],
        ttl_classes[peripheral["bank_direction_high"]])


def peripheral_urukul(module, peripheral):
    if len(peripheral["ports"]) == 1:
        port, port_aux = peripheral["ports"][0], None
    elif len(peripheral["ports"]) == 2:
        port, port_aux = peripheral["ports"]
    else:
        raise ValueError("wrong number of ports")
    if peripheral.get("synchronization", False):
        sync_gen_cls = ttl_simple.ClockGen
    else:
        sync_gen_cls = None
    eem.Urukul.add_std(module, port, port_aux, ttl_serdes_7series.Output_8X,
        sync_gen_cls)


def peripheral_sampler(module, peripheral):
    if len(peripheral["ports"]) == 1:
        port, port_aux = peripheral["ports"][0], None
    elif len(peripheral["ports"]) == 2:
        port, port_aux = peripheral["ports"]
    else:
        raise ValueError("wrong number of ports")
    eem.Sampler.add_std(module, port, port_aux, ttl_serdes_7series.Output_8X)


def peripheral_zotino(module, peripheral):
    if len(peripheral["ports"]) != 1:
        raise ValueError("wrong number of ports")
    eem.Zotino.add_std(module, peripheral["ports"][0],
        ttl_serdes_7series.Output_8X)


def peripheral_grabber(module, peripheral):
    if len(peripheral["ports"]) == 1:
        port, port_aux = peripheral["ports"][0], None
    elif len(peripheral["ports"]) == 2:
        port, port_aux = peripheral["ports"]
    else:
        raise ValueError("wrong number of ports")
    eem.Grabber.add_std(module, port, port_aux)


def add_peripherals(module, peripherals):
    peripheral_processors = {
        "dio": peripheral_dio,
        "urukul": peripheral_urukul,
        "sampler": peripheral_sampler,
        "zotino": peripheral_zotino,
        "grabber": peripheral_grabber,
    }
    for peripheral in peripherals:
        peripheral_processors[peripheral["type"]](module, peripheral)


class GenericStandalone(StandaloneBase):
    def __init__(self, description, hw_rev=None,**kwargs):
        if hw_rev is None:
            hw_rev = description["hw_rev"]
        StandaloneBase.__init__(self, hw_rev=hw_rev, **kwargs)

        self.config["SI5324_AS_SYNTHESIZER"] = None
        self.config["RTIO_FREQUENCY"] = "{:.1f}".format(description.get("rtio_frequency", 125e6)/1e6)
        if hw_rev == "v1.0":
            # EEM clock fan-out from Si5324, not MMCX
            self.comb += self.platform.request("clk_sel").eq(1)

        has_grabber = any(peripheral["type"] == "grabber" for peripheral in description["peripherals"])
        if has_grabber:
            self.grabber_csr_group = []

        self.rtio_channels = []
        add_peripherals(self, description["peripherals"])
        for i in (1, 2):
            print("SFP LED at RTIO channel {}".format(len(self.rtio_channels)))
            sfp_ctl = self.platform.request("sfp_ctl", i)
            phy = ttl_simple.Output(sfp_ctl.led)
            self.submodules += phy
            self.rtio_channels.append(rtio.Channel.from_phy(phy))

        self.config["HAS_RTIO_LOG"] = None
        self.config["RTIO_LOG_CHANNEL"] = len(self.rtio_channels)
        self.rtio_channels.append(rtio.LogChannel())

        self.add_rtio(self.rtio_channels)
        if has_grabber:
            self.config["HAS_GRABBER"] = None
            self.add_csr_group("grabber", self.grabber_csr_group)
            for grabber in self.grabber_csr_group:
                self.platform.add_false_path_constraints(
                    self.rtio_crg.cd_rtio.clk, getattr(self, grabber).deserializer.cd_cl.clk)


class GenericMaster(MasterBase):
    def __init__(self, description, hw_rev=None, **kwargs):
        if hw_rev is None:
            hw_rev = description["hw_rev"]
        MasterBase.__init__(self,
            hw_rev=hw_rev,
            rtio_clk_freq=description.get("rtio_frequency", 125e6),
            enable_sata=description.get("enable_sata_drtio", False),
            **kwargs)
        if hw_rev == "v1.0":
            # EEM clock fan-out from Si5324, not MMCX
            self.comb += self.platform.request("clk_sel").eq(1)

        has_grabber = any(peripheral["type"] == "grabber" for peripheral in description["peripherals"])
        if has_grabber:
            self.grabber_csr_group = []

        self.rtio_channels = []
        add_peripherals(self, description["peripherals"])
        self.config["HAS_RTIO_LOG"] = None
        self.config["RTIO_LOG_CHANNEL"] = len(self.rtio_channels)
        self.rtio_channels.append(rtio.LogChannel())

        self.add_rtio(self.rtio_channels)
        if has_grabber:
            self.config["HAS_GRABBER"] = None
            self.add_csr_group("grabber", self.grabber_csr_group)
            for grabber in self.grabber_csr_group:
                self.platform.add_false_path_constraints(
                    self.drtio_transceiver.gtps[0].txoutclk, getattr(self, grabber).deserializer.cd_cl.clk)


class GenericSatellite(SatelliteBase):
    def __init__(self, description, hw_rev=None, **kwargs):
        if hw_rev is None:
            hw_rev = description["hw_rev"]
        SatelliteBase.__init__(self,
                               hw_rev=hw_rev,
                               rtio_clk_freq=description.get("rtio_frequency", 125e6),
                               enable_sata=description.get("enable_sata_drtio", False),
                               **kwargs)
        if hw_rev == "v1.0":
            # EEM clock fan-out from Si5324, not MMCX
            self.comb += self.platform.request("clk_sel").eq(1)

        has_grabber = any(peripheral["type"] == "grabber" for peripheral in description["peripherals"])
        if has_grabber:
            self.grabber_csr_group = []

        self.rtio_channels = []
        add_peripherals(self, description["peripherals"])
        self.config["HAS_RTIO_LOG"] = None
        self.config["RTIO_LOG_CHANNEL"] = len(self.rtio_channels)
        self.rtio_channels.append(rtio.LogChannel())

        self.add_rtio(self.rtio_channels)
        if has_grabber:
            self.config["HAS_GRABBER"] = None
            self.add_csr_group("grabber", self.grabber_csr_group)
            for grabber in self.grabber_csr_group:
                self.platform.add_false_path_constraints(
                    self.drtio_transceiver.gtps[0].txoutclk, getattr(self, grabber).deserializer.cd_cl.clk)


def main():
    parser = argparse.ArgumentParser(
        description="ARTIQ device binary builder for generic Kasli systems")
    builder_args(parser)
    soc_kasli_args(parser)
    parser.set_defaults(output_dir="artiq_kasli")
    parser.add_argument("description", metavar="DESCRIPTION",
                        help="JSON system description file")
    args = parser.parse_args()

    with open(args.description, "r") as f:
        description = json.load(f)

    if description["target"] != "kasli":
        raise ValueError("Description is for a different target")

    if description["base"] == "standalone":
        cls = GenericStandalone
    elif description["base"] == "master":
        cls = GenericMaster
    elif description["base"] == "satellite":
        cls = GenericSatellite
    else:
        raise ValueError("Invalid base")

    soc = cls(description, **soc_kasli_argdict(args))
    soc.class_name_override = description["variant"]
    args.variant = description["variant"]
    build_artiq_soc(soc, builder_argdict(args))


if __name__ == "__main__":
    main()
