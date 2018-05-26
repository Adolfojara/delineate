#! /usr/bin/env python
# -*- coding: utf-8 -*-

###############################################################################
##
##  Copyright 2018 Jeet Sukumaran and Mark T. Holder.
##
##  This program is free software; you can redistribute it and/or modify
##  it under the terms of the GNU General Public License as published by
##  the Free Software Foundation; either version 3 of the License, or
##  (at your option) any later version.
##
##  This program is distributed in the hope that it will be useful,
##  but WITHOUT ANY WARRANTY; without even the implied warranty of
##  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
##  GNU General Public License for more details.
##
##  You should have received a copy of the GNU General Public License along
##  with this program. If not, see <http://www.gnu.org/licenses/>.
##
###############################################################################

"""
This program does something.
"""

import sys
import os
import re
import argparse
import json
import collections
import scipy.optimize
import math
from delineate import model

__prog__ = os.path.basename(__file__)
__version__ = "1.0.0"
__description__ = __doc__
__author__ = 'Jeet Sukumaran and Mark T. Holder'
__copyright__ = 'Copyright (C) 2018 Jeet Sukumaran and Mark T. Holder.'

def parse_fieldname_and_value(labels):
    if not labels:
        return collections.OrderedDict()
    fieldname_value_map = collections.OrderedDict()
    for label in labels:
        match = re.match(r"\s*(.*?)\s*:\s*(.*)\s*", label)
        if not match:
            raise ValueError("Cannot parse fieldname and label (format required: fieldname:value): {}".format(label))
        fieldname, value = match.groups(0)
        fieldname_value_map[fieldname] = value
    return fieldname_value_map

class MaximumLikelihoodEstimator(object):

    def __init__(self,
            tree,
            species_leaf_sets,
            initial_speciation_rate,
            min_speciation_rate,
            max_speciation_rate):
        self.tree = tree
        self.species_leaf_sets = species_leaf_sets
        self.initial_speciation_rate = initial_speciation_rate
        self.min_speciation_rate = min_speciation_rate
        self.max_speciation_rate = max_speciation_rate
        assert self.min_speciation_rate > 0.0
        assert self.min_speciation_rate <= self.max_speciation_rate
        assert self.min_speciation_rate <= self.initial_speciation_rate
        assert self.max_speciation_rate >= self.initial_speciation_rate
        self._set_up_node_constraints()

    def _set_up_node_constraints(self):
        # Set up per-node conspecific and non-conspecific constraints...
        sls_by_species = {}
        self.all_monotypic = True
        for spls in self.species_leaf_sets:
            if len(spls) > 1:
                self.all_monotypic = False
            for sp in spls:
                sls_by_species[sp] = spls
        for nd in self.tree.postorder_node_iter():
            nd.speciation_allowed = True
            if nd.is_leaf():
                nd.leaf_label_set = frozenset([nd.taxon.label])
                sp = sls_by_species[nd.taxon.label]
                nd.speciation_allowed = len(sp) == 1
                nd.sp_set = set([sls_by_species[nd.taxon.label]])
            else:
                lls = set()
                for c in nd.child_nodes():
                    lls.update(c.leaf_label_set)
                nd.leaf_label_set = frozenset(lls)
                nd.sp_set = set([sls_by_species[i] for i in nd.leaf_label_set])
                dup_sp = None
                for sp in nd.sp_set:
                    if not nd.leaf_label_set.issuperset(sp):
                        nd.speciation_allowed = False
                    found = False
                    for c in nd.child_nodes():
                        if sp in c.sp_set:
                            if found:
                                if dup_sp is None:
                                    dup_sp = sp
                                else:
                                    m = 'More than 1 species is conspecific with this ancestor. This is not allowed. Leaf sets of offending species:  {}\n  {}\n'
                                    m = m.format(sp, dup_sp)
                                    raise ValueError(m)
                                break
                            found = True
                not_consp = []
                for sp in nd.sp_set:
                    not_consp.extend(self._calc_new_nonconsp(nd, sp))
                if not_consp:
                    nd.sp_constraints = {'not_conspecific': not_consp}

    def _calc_new_nonconsp(self, nd, species):
        not_consp = []
        for c in nd.child_nodes():
            if species not in c.sp_set:
                first_label = list(species)[0]
                for cs in c.sp_set:
                    fcl = list(cs)[0]
                    not_consp.append((first_label, fcl))
        return not_consp

    def _estimate(self,
            f,
            initial_val,
            min_val,
            max_val):
        assert min_val > 0.0
        assert min_val <= max_val
        assert min_val <= initial_val
        assert max_val >= initial_val
        est_result = scipy.optimize.minimize_scalar(f, method="bounded", bounds=(min_val, max_val))
        return est_result.x, est_result.fun
        # brac_res = scipy.optimize.bracket(f,
        #         xa=min_val,
        #         xb=max_val,
        #         )
        # b = brac_res[:3]
        # if b[0] <= 0:
        #     b[0] = 1e-8
        # sys.stderr.write("brackets: {}\n".format(b))
        # while True:
        #     try:
        #         # est_result = scipy.optimize.brent(f, brack=b, full_output=True)
        #         est_result = scipy.optimize.minimize_scalar(f, bounds=b)
        #         break
        #     except ValueError:
        #         # weird bracket interval; default to min/max bounds
        #         b = (min_val, initial_val, max_val)
        #         est_result = scipy.optimize.brent(f, brack=b, full_output=True)
        # value_estimate = est_result[0]
        # value_estimate_prob = est_result[1]
        # return value_estimate, value_estimate_prob

    def estimate_speciation_rate(self):
        if len(self.species_leaf_sets) == 1:
            speciation_completion_rate_estimate = 0.0
            self.tree.speciation_completion_rate = speciation_completion_rate_estimate
            speciation_completion_rate_estimate_prob = self.tree.calc_joint_probability_of_species(taxon_labels=self.species_leaf_sets)
        elif self.all_monotypic:
            speciation_completion_rate_estimate = float('inf')
            self.tree.speciation_completion_rate = speciation_completion_rate_estimate
            speciation_completion_rate_estimate_prob = self.tree.calc_joint_probability_of_species(taxon_labels=self.species_leaf_sets)
        else:
            def f(x, *args):
                self.tree.speciation_completion_rate = x
                return -1 * self.tree.calc_joint_probability_of_species(taxon_labels=self.species_leaf_sets)
            x1, x2 = self._estimate(f=f,
                    initial_val=self.initial_speciation_rate,
                    min_val=self.min_speciation_rate,
                    max_val=self.max_speciation_rate,
                    )
            speciation_completion_rate_estimate = x1
            speciation_completion_rate_estimate_prob = -1 * x2
            return speciation_completion_rate_estimate, math.log(speciation_completion_rate_estimate_prob)

    def estimate_confidence_interval(self, mle_speciation_rate, max_lnl):
        def f0(x, *args):
            self.tree.speciation_completion_rate = x
            prob = self.tree.calc_joint_probability_of_species(taxon_labels=self.species_leaf_sets)
            try:
                return abs(max_lnl - 1.96 - math.log(prob))
            except ValueError:
                sys.stderr.write("x = {}, prob = {}\n".format(x, prob))
                raise
        min_val = self.min_speciation_rate
        max_val = mle_speciation_rate - 1e-8
        initial_val = min_val + ((max_val - min_val) / 2.0)
        ci_low, _ = self._estimate(f0,
                initial_val=initial_val,
                min_val=min_val,
                max_val=max_val)
        min_val = mle_speciation_rate + 1e-8
        max_val = self.max_speciation_rate
        initial_val = min_val + ((max_val - min_val) / 2.0)
        ci_high, _ = self._estimate(f0,
                initial_val=initial_val,
                min_val=min_val,
                max_val=max_val)
        return ci_low, ci_high

def main():
    """
    Main CLI handler.
    """

    parser = argparse.ArgumentParser(description=__description__)

    source_options = parser.add_argument_group("Source options")

    source_options.add_argument("-t", "--tree-file",
            nargs=1,
            help="Path to tree file.")

    source_options.add_argument("-c", "--config-file",
            help="Path to configuration file.")

    source_options.add_argument("-f", "--format",
            dest="data_format",
            type=str,
            default="nexus",
            choices=["nexus", "newick"],
            help="Input data format (default='%(default)s').")

    estimation_options = parser.add_argument_group("Estimation options")
    estimation_options.add_argument("-i", "--intervals", "--confidence-intervals",
            action="store_true",
            help="Calculate confidence intervals.",)
    output_options = parser.add_argument_group("Output options")
    output_options.add_argument("-I", "--tree-info",
            action="store_true",
            help="Output additional information about the tree",)
    output_options.add_argument("-l", "--label",
            action="append",
            help="Label to append to output (in format <FIELD-NAME>:value;)")
    output_options.add_argument( "--no-header-row",
            action="store_true",
            default=False,
            help="Do not write a header row.")
    output_options.add_argument( "--append",
            action="store_true",
            default=False,
            help="Append to output file if it already exists instead of overwriting.")

    args = parser.parse_args()
    args.separator = "\t"
    tree = model.LineageTree.get(
            path=args.tree_file[0],
            schema=args.data_format,
            )
    with open(args.config_file) as src:
        config = json.load(src)
    species_leaf_sets = model._Partition.compile_lookup_key( config["species_leaf_sets"] )
    initial_speciation_rate = config.pop("initial_speciation_rate", 0.01)
    min_speciation_rate = config.pop("min_speciation_rate", 1e-8)
    max_speciation_rate = config.pop("max_speciation_rate", 2.00)
    mle = MaximumLikelihoodEstimator(
            tree=tree,
            species_leaf_sets=species_leaf_sets,
            initial_speciation_rate=initial_speciation_rate,
            min_speciation_rate=min_speciation_rate,
            max_speciation_rate=max_speciation_rate)
    speciation_completion_rate_estimate, speciation_completion_rate_estimate_lnl = mle.estimate_speciation_rate()
    extra_fields = parse_fieldname_and_value(args.label)
    if not args.no_header_row:
        header_row = []
        if args.tree_info:
            header_row.append("numTips")
            header_row.append("rootAge")
        header_row.extend(extra_fields)
        header_row.append("estSpCompRate")
        header_row.append("estSpCompRateLnL")
        if args.intervals:
            header_row.append("ciLow")
            header_row.append("ciHigh")
        sys.stdout.write(args.separator.join(header_row))
        sys.stdout.write("\n")
    row = []
    if args.tree_info:
        row.append("{}".format(len(tree.taxon_namespace)))
        tree.calc_node_ages()
        row.append("{}".format(tree.seed_node.age))
    for field in extra_fields:
        row.append(extra_fields[field])
    row.append("{}".format(speciation_completion_rate_estimate))
    row.append("{}".format(speciation_completion_rate_estimate_lnl))
    if args.intervals:
        ci_low, ci_high = mle.estimate_confidence_interval(
            mle_speciation_rate=speciation_completion_rate_estimate,
            max_lnl=speciation_completion_rate_estimate_lnl)
        row.append("{}".format(ci_low))
        row.append("{}".format(ci_high))
    sys.stdout.write(args.separator.join(row))
    sys.stdout.write("\n")

if __name__ == '__main__':
    main()


