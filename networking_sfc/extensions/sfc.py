# Copyright 2015 Futurewei. All rights reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from abc import ABCMeta
from abc import abstractmethod

import six

from neutron_lib.api import converters as lib_converters
from neutron_lib.api import extensions
from neutron_lib.api import validators as lib_validators
from neutron_lib.db import constants as db_const
from neutron_lib import exceptions as neutron_exc
from oslo_config import cfg

from neutron.api import extensions as neutron_ext
from neutron.api.v2 import resource_helper
from neutron.services import service_base

from networking_sfc._i18n import _
from networking_sfc import extensions as sfc_extensions

cfg.CONF.import_opt('api_extensions_path', 'neutron.common.config')
neutron_ext.append_api_extensions_path(sfc_extensions.__path__)

SFC_EXT = "sfc"
SFC_PREFIX = "/sfc"

DEFAULT_CHAIN_CORRELATION = 'mpls'
DEFAULT_CHAIN_SYMMETRY = False
DEFAULT_CHAIN_PARAMETERS = {'correlation': DEFAULT_CHAIN_CORRELATION,
                            'symmetric': DEFAULT_CHAIN_SYMMETRY}
DEFAULT_SF_PARAMETERS = {'correlation': None, 'weight': 1}
DEFAULT_PPG_PARAMETERS = {'lb_fields': []}
SUPPORTED_LB_FIELDS = [
    "eth_src", "eth_dst", "ip_src", "ip_dst",
    "tcp_src", "tcp_dst", "udp_src", "udp_dst"
]
MAX_CHAIN_ID = 65535


# NOTE(scsnow): move to neutron-lib
def validate_list_of_allowed_values(data, allowed_values=None):
    if not isinstance(data, list):
        msg = _("'%s' is not a list") % data
        return msg

    illegal_values = set(data) - set(allowed_values)
    if illegal_values:
        msg = _("Illegal values in a list: %s") % ', '.join(illegal_values)
        return msg


lib_validators.validators['type:list_of_allowed_values'] = \
    validate_list_of_allowed_values


# Port Chain Exceptions
class PortChainNotFound(neutron_exc.NotFound):
    message = _("Port Chain %(id)s not found.")


class PortChainUnavailableChainId(neutron_exc.InvalidInput):
    message = _("Port Chain %(id)s no available chain id.")


class PortChainFlowClassifierInConflict(neutron_exc.InvalidInput):
    message = _("Flow Classifier %(fc_id)s conflicts with "
                "Flow Classifier %(pc_fc_id)s in port chain %(pc_id)s.")


class PortChainChainIdInConflict(neutron_exc.InvalidInput):
    message = _("Chain id %(chain_id)s conflicts with "
                "Chain id in port chain %(pc_id)s.")


class PortPairGroupNotSpecified(neutron_exc.InvalidInput):
    message = _("Port Pair Group is not specified in Port Chain.")


class InvalidPortPairGroups(neutron_exc.InUse):
    message = _("Port Pair Group(s) %(port_pair_groups)s in use by "
                "Port Chain %(port_chain)s.")


class PortPairPortNotFound(neutron_exc.NotFound):
    message = _("Port Pair port %(id)s not found.")


class PortPairIngressEgressDifferentHost(neutron_exc.InvalidInput):
    message = _("Port Pair ingress port %(ingress)s and"
                "egress port %(egress)s not in the same host.")


class PortPairIngressNoHost(neutron_exc.InvalidInput):
    message = _("Port Pair ingress port %(ingress)s does not "
                "belong to a host.")


class PortPairEgressNoHost(neutron_exc.InvalidInput):
    message = _("Port Pair egress port %(egress)s does not "
                "belong to a host.")


class PortPairIngressEgressInUse(neutron_exc.InvalidInput):
    message = _("Port Pair with ingress port %(ingress)s "
                "and egress port %(egress)s is already used by "
                "another Port Pair %(id)s.")


class PortPairNotFound(neutron_exc.NotFound):
    message = _("Port Pair %(id)s not found.")


class PortPairGroupNotFound(neutron_exc.NotFound):
    message = _("Port Pair Group %(id)s not found.")


class PortPairGroupInUse(neutron_exc.InUse):
    message = _("Port Pair Group %(id)s in use.")


class PortPairInUse(neutron_exc.InUse):
    message = _("Port Pair %(id)s in use.")


def normalize_port_pair_groups(port_pair_groups):
    port_pair_groups = lib_converters.convert_to_list(port_pair_groups)
    if not port_pair_groups:
        raise PortPairGroupNotSpecified()
    return port_pair_groups


def normalize_chain_parameters(parameters):
    if not parameters:
        return DEFAULT_CHAIN_PARAMETERS
    if 'correlation' not in parameters:
        parameters['correlation'] = DEFAULT_CHAIN_CORRELATION
    if 'symmetric' not in parameters:
        parameters['symmetric'] = DEFAULT_CHAIN_SYMMETRY
    return parameters


def normalize_sf_parameters(parameters):
    return parameters if parameters else DEFAULT_SF_PARAMETERS


def normalize_ppg_parameters(parameters):
    return parameters if parameters else DEFAULT_PPG_PARAMETERS


RESOURCE_ATTRIBUTE_MAP = {
    'port_pairs': {
        'id': {
            'allow_post': False, 'allow_put': False,
            'is_visible': True,
            'validate': {'type:uuid': None},
            'primary_key': True
        },
        'name': {
            'allow_post': True, 'allow_put': True,
            'is_visible': True, 'default': '',
            'validate': {'type:string': db_const.NAME_FIELD_SIZE},
        },
        'description': {
            'allow_post': True, 'allow_put': True,
            'is_visible': True, 'default': '',
            'validate': {'type:string': db_const.DESCRIPTION_FIELD_SIZE},
        },
        'tenant_id': {
            'allow_post': True, 'allow_put': False,
            'is_visible': True,
            'validate': {'type:string': db_const.PROJECT_ID_FIELD_SIZE},
            'required_by_policy': True
        },
        'ingress': {
            'allow_post': True, 'allow_put': False,
            'is_visible': True,
            'validate': {'type:uuid': None}
        },
        'egress': {
            'allow_post': True, 'allow_put': False,
            'is_visible': True,
            'validate': {'type:uuid': None}
        },
        'service_function_parameters': {
            'allow_post': True, 'allow_put': False,
            'is_visible': True, 'default': None,
            'validate': {
                'type:dict': {
                    'correlation': {
                        'default': DEFAULT_SF_PARAMETERS['correlation'],
                        'type:values': [None]
                    },
                    'weight': {
                        'default': DEFAULT_SF_PARAMETERS['weight'],
                        'type:non_negative': None,
                        'convert_to': lib_converters.convert_to_int
                    }
                }
            },
            'convert_to': normalize_sf_parameters
        }
    },
    'port_chains': {
        'id': {
            'allow_post': False, 'allow_put': False,
            'is_visible': True,
            'validate': {'type:uuid': None},
            'primary_key': True
        },
        'chain_id': {
            'allow_post': True, 'allow_put': False,
            'is_visible': True, 'default': 0,
            'validate': {'type:range': (0, MAX_CHAIN_ID)},
            'convert_to': lib_converters.convert_to_int
        },
        'name': {
            'allow_post': True, 'allow_put': True,
            'is_visible': True, 'default': '',
            'validate': {'type:string': db_const.NAME_FIELD_SIZE},
        },
        'description': {
            'allow_post': True, 'allow_put': True,
            'is_visible': True, 'default': '',
            'validate': {'type:string': db_const.DESCRIPTION_FIELD_SIZE},
        },
        'tenant_id': {
            'allow_post': True, 'allow_put': False,
            'is_visible': True,
            'validate': {'type:string': db_const.PROJECT_ID_FIELD_SIZE},
            'required_by_policy': True
        },
        'port_pair_groups': {
            'allow_post': True, 'allow_put': True,
            'is_visible': True,
            'validate': {'type:uuid_list': None},
            'convert_to': normalize_port_pair_groups
        },
        'flow_classifiers': {
            'allow_post': True, 'allow_put': True,
            'is_visible': True, 'default': None,
            'validate': {'type:uuid_list': None},
            'convert_to': lib_converters.convert_to_list
        },
        'chain_parameters': {
            'allow_post': True, 'allow_put': False,
            'is_visible': True, 'default': None,
            'validate': {
                'type:dict': {
                    'correlation': {
                        'default': DEFAULT_CHAIN_PARAMETERS['correlation'],
                        'type:values': ['mpls']
                    },
                    'symmetric': {
                        'default': DEFAULT_CHAIN_PARAMETERS['symmetric'],
                        'convert_to': lib_converters.convert_to_boolean
                    }
                }
            },
            'convert_to': normalize_chain_parameters
        }
    },
    'port_pair_groups': {
        'id': {
            'allow_post': False, 'allow_put': False,
            'is_visible': True,
            'validate': {'type:uuid': None},
            'primary_key': True},
        'group_id': {
            'allow_post': False, 'allow_put': False,
            'is_visible': True
        },
        'name': {
            'allow_post': True, 'allow_put': True,
            'is_visible': True, 'default': '',
            'validate': {'type:string': db_const.NAME_FIELD_SIZE},
        },
        'description': {
            'allow_post': True, 'allow_put': True,
            'is_visible': True, 'default': '',
            'validate': {'type:string': db_const.DESCRIPTION_FIELD_SIZE},
        },
        'tenant_id': {
            'allow_post': True, 'allow_put': False,
            'is_visible': True,
            'validate': {'type:string': db_const.PROJECT_ID_FIELD_SIZE},
            'required_by_policy': True
        },
        'port_pairs': {
            'allow_post': True, 'allow_put': True,
            'is_visible': True, 'default': None,
            'validate': {'type:uuid_list': None},
            'convert_to': lib_converters.convert_none_to_empty_list
        },
        'port_pair_group_parameters': {
            'allow_post': True, 'allow_put': False,
            'is_visible': True, 'default': None,
            'validate': {
                'type:dict': {
                    'lb_fields': {
                        'default': DEFAULT_PPG_PARAMETERS['lb_fields'],
                        'type:list_of_allowed_values': SUPPORTED_LB_FIELDS
                    }
                }
            },
            'convert_to': normalize_ppg_parameters
        }
    }
}

sfc_quota_opts = [
    cfg.IntOpt('quota_port_chain',
               default=10,
               help=_('Maximum number of port chains per tenant. '
                      'A negative value means unlimited.')),
    cfg.IntOpt('quota_port_pair_group',
               default=10,
               help=_('maximum number of port pair group per tenant. '
                      'a negative value means unlimited.')),
    cfg.IntOpt('quota_port_pair',
               default=100,
               help=_('maximum number of port pair per tenant. '
                      'a negative value means unlimited.'))
]

cfg.CONF.register_opts(sfc_quota_opts, 'QUOTAS')


class Sfc(extensions.ExtensionDescriptor):
    """Service Function Chain extension."""

    @classmethod
    def get_name(cls):
        return "Service Function Chaining"

    @classmethod
    def get_alias(cls):
        return SFC_EXT

    @classmethod
    def get_description(cls):
        return "Service Function Chain extension."

    @classmethod
    def get_plugin_interface(cls):
        return SfcPluginBase

    @classmethod
    def get_updated(cls):
        return "2015-10-05T10:00:00-00:00"

    def update_attributes_map(self, attributes):
        super(Sfc, self).update_attributes_map(
            attributes, extension_attrs_map=RESOURCE_ATTRIBUTE_MAP)

    @classmethod
    def get_resources(cls):
        """Returns Ext Resources."""
        plural_mappings = resource_helper.build_plural_mappings(
            {}, RESOURCE_ATTRIBUTE_MAP)
        plural_mappings['sfcs'] = 'sfc'
        return resource_helper.build_resource_info(
            plural_mappings,
            RESOURCE_ATTRIBUTE_MAP,
            SFC_EXT,
            register_quota=True)

    def get_extended_resources(self, version):
        if version == "2.0":
            return RESOURCE_ATTRIBUTE_MAP
        else:
            return {}


@six.add_metaclass(ABCMeta)
class SfcPluginBase(service_base.ServicePluginBase):

    def get_plugin_name(self):
        return SFC_EXT

    def get_plugin_type(self):
        return SFC_EXT

    def get_plugin_description(self):
        return 'SFC service plugin for service chaining.'

    @abstractmethod
    def create_port_chain(self, context, port_chain):
        pass

    @abstractmethod
    def update_port_chain(self, context, id, port_chain):
        pass

    @abstractmethod
    def delete_port_chain(self, context, id):
        pass

    @abstractmethod
    def get_port_chains(self, context, filters=None, fields=None,
                        sorts=None, limit=None, marker=None,
                        page_reverse=False):
        pass

    @abstractmethod
    def get_port_chain(self, context, id, fields=None):
        pass

    @abstractmethod
    def create_port_pair_group(self, context, port_pair_group):
        pass

    @abstractmethod
    def update_port_pair_group(self, context, id, port_pair_group):
        pass

    @abstractmethod
    def delete_port_pair_group(self, context, id):
        pass

    @abstractmethod
    def get_port_pair_groups(self, context, filters=None, fields=None,
                             sorts=None, limit=None, marker=None,
                             page_reverse=False):
        pass

    @abstractmethod
    def get_port_pair_group(self, context, id, fields=None):
        pass

    @abstractmethod
    def create_port_pair(self, context, port_pair):
        pass

    @abstractmethod
    def update_port_pair(self, context, id, port_pair):
        pass

    @abstractmethod
    def delete_port_pair(self, context, id):
        pass

    @abstractmethod
    def get_port_pairs(self, context, filters=None, fields=None,
                       sorts=None, limit=None, marker=None,
                       page_reverse=False):
        pass

    @abstractmethod
    def get_port_pair(self, context, id, fields=None):
        pass
