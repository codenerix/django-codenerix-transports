# -*- coding: utf-8 -*-
#
# django-codenerix-transports
#
# Copyright 2017 Centrologic Computational Logistic Center S.L.
#
# Project URL : http://www.codenerix.com
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from suds.client import Client

from django.db import models
from django.utils.translation import ugettext as _
from django.core.validators import MaxValueValidator
from django_countries.fields import CountryField
from django.conf import settings

from codenerix.models import CodenerixModel

TRANSPORT_PROTOCOL_CHOICES = (
    ('mrw', _('MRW')),
    ('seur', _('SEUR')),
)


class TransportRequest(CodenerixModel):
    '''
    ref: used to store the reference on the remote system (mrw, seur, correos,...), it is separated for quicker location
    reverse: used to store the reverse URL for this request when we get back an user from a remote system
    platform: selected platform for transport to happen (it is linked to data)
    protocol: selected protocol for payment to happen (it is linked to request/answer)
        - MRW only for countries: ES, PT, AD & GI
    request/answer: usable structure for the selected payment system
    '''
    # Control
    ref = models.CharField(_('Reference'), max_length=15, blank=False, null=True, default=None)
    reverse = models.CharField(_('Reverse'), max_length=64, blank=False, null=False)
    platform = models.CharField(_('Platform'), max_length=20, blank=False, null=False)
    protocol = models.CharField(_('Protocol'), choices=TRANSPORT_PROTOCOL_CHOICES, max_length=10, blank=False, null=False)
    real = models.BooleanField(_('Real'), blank=False, null=False, default=False)
    error = models.BooleanField(_('Error'), blank=False, null=False, default=False)
    error_txt = models.TextField(_('Error Text'), blank=True, null=True)
    cancelled = models.BooleanField(_('Cancelled'), blank=False, null=False, default=False)
    notes = models.CharField(_('Notes'), max_length=30, blank=True, null=True)    # Observaciones
    
    # Info
    origin_address = models.CharField(_('Origin Address'), max_length=30, blank=True, null=True)
    origin_country = CountryField(_('Origin Country'), blank=False)
    destination_address = models.CharField(_('Destination Address'), max_length=30, blank=True, null=True)
    destination_country = CountryField(_('Destination Country'), blank=False)
    
    # Debug data
    request = models.TextField(_('Request'), blank=True, null=True)
    answer = models.TextField(_('Answer'), blank=True, null=True)
    request_date = models.DateTimeField(_("Request date"), editable=False, blank=True, null=True)
    answer_date = models.DateTimeField(_("Answer date"), editable=False, blank=True, null=True)
    
    class Meta:
        unique_together = ('ref', 'platform')
    
    def __unicode__(self):
        return u"TransReq({0})_{1}:{2}|{3}:{4}[{5}]".format(self.pk, self.platform, self.protocol, self.ref, self.total, self.order)
    
    def __fields__(self, info):
        fields = []
        fields.append(('ref', _('Reference'), 100))
        fields.append(('platform', _('Platform'), 100))
        fields.append(('protocol', _('Protocol'), 100))
        return fields
    
    def test_packages(self):
        for package in self.packages.all():
            attributes = ['locator']
            methods = ['length', 'width', 'height', 'weight', 'value', 'notes']
            for check in attributes + methods:
                attr = getattr(package, check, None)
                if not attr:
                    raise IOError("I found a package which doesn't implement TransportBox class: {} ['{}' attribute not implemented]".format(package, check))
                elif check in methods:
                    if type(attr) != type(self.test_packages):
                        raise IOError("I found a pakcage wich doesn't implement TransportBox class properly: {} ('{}' is not a method)".format(package, check))
        
    def query(self):
        # Test for package integrity
        self.test_packages()
        
        # Get config
        meta = settings.PAYMENTS.get('meta', {})
        config = settings.TRANSPORTS.get(self.platform, {})
        
        # Autoset environment
        self.real = meta.get('real', False)
        # Autoset protocol
        self.protocol = None
        protocol = config.get('protocol', None)
        for (key, name) in TRANSPORT_PROTOCOL_CHOICES:
            if key == protocol:
                self.protocol = key
        if self.protocol is None:
            raise TransportError((3, "Unknown platform '{}'".format(self.platform)))
        elif config:
            if self.real == meta.get('real', False):
                if self.protocol == 'mrw':
                    self.__query_mrw(meta, config)
                elif self.protocol == 'seur':
                    self.__query_seur(meta, config)
                else:
                    raise TransportError((1, "Unknown protocol '{}'".format(self.protocol)))
            else:
                # Request and configuration do not match
                if meta.get('real', False):
                    envsys = 'REAL'
                else:
                    envsys = 'TEST'
                if self.real:
                    envself = 'REAL'
                else:
                    envself = 'TEST'
                raise TransportError((2, "Wrong environment: this transaction is for '{}' environment and system is set to '{}'".format(envself, envsys)))
        else:
            raise TransportError((3, "Platform '{}' not configured in your system".format(self.platform)))
    
    def __query_mrw(self, meta, config):
        # Set endpoint
        if self.real:
            endpoint = ''
            raise IOError("No endpoint defined for MRW REAL")
        else:
            endpoint = 'http://sagec-test.mrw.es/MRWEnvio.asmx?WSDL'
        
        # Build the SOAP instance
        client = Client(endpoint)
        
        # Authentication
        auth = client.factory.create('AuthInfo')
        auth["CodigoFranquicia"] = config.get('franchise', None)
        auth['CodigoAbonado'] = config.get('client', None)
        auth['CodigoDepartamento'] = config.get('department', None)
        auth['UserName'] = config.get('username', None)
        auth['Password'] = config.get('password', None)
        
        # Request
        datas = client.factory.create('TransmEnvioRequest')
        datas["DatosEntrega"]["Direccion"]["CodigoTipoVia"] = 'CL'
        datas["DatosEntrega"]["Direccion"]["Via"] = 'CL'
        datas["DatosEntrega"]["Direccion"]["Numero"] = 3
        datas["DatosEntrega"]["Direccion"]["Resto"] = 'opcional'
        datas["DatosEntrega"]["Direccion"]["CodigoPostal"] = 29011
        datas["DatosEntrega"]["Direccion"]["Poblacion"] = 'Malaga'
        datas["DatosEntrega"]["Nif"] = '12345678z'
        datas["DatosEntrega"]["Nombre"] = '12345678z'
        datas["DatosEntrega"]["Telefono"] = '12345678z'
        datas["DatosEntrega"]["Contacto"] = '12345678z'
        datas["DatosEntrega"]["ALaAtencionDe"] = '12345678z'
        datas["DatosEntrega"]["Horario"] = ['03:30', '22:22']
        datas["DatosEntrega"]["Observaciones"] = 'opcional'
        
        datas["DatosServicio"]["Fecha"] = '02/02/2002'
        datas["DatosServicio"]["Referencia"] = 123
        datas["DatosServicio"]["EnFranquicia"] = 'N'
        datas["DatosServicio"]["CodigoServicio"] = '0110'
        # datas["DatosServicio"]["Frecuencia"] = '0110' # solo en caso de que el CodigoServicio sea 0005
        # datas["DatosServicio"]["CodigoPromocion"] = '0110' # solo en caso de promocion
        datas["DatosServicio"]["NumeroSobre"] = 0
        datas["DatosServicio"]["Bultos"] = [12, 12, 12]  # en cm (ancho, largo, ancho)
        datas["DatosServicio"]["NumeroBultos"] = 3
        datas["DatosServicio"]["Peso"] = 3  # en kg
        # datas["DatosServicio"]["NumeroPuentes"] =
        datas["DatosServicio"]["EntregaSabado"] = 'N'
        datas["DatosServicio"]["Entrega830"] = 'N'  # opcional
        datas["DatosServicio"]["EntregaPartirDe"] = ''
        datas["DatosServicio"]["Gestion"] = 'N'  # opcional
        datas["DatosServicio"]["Retorno"] = 'S'  # opcional
        datas["DatosServicio"]["ConfirmacionInmediata"] = 'N'  # opcional
        datas["DatosServicio"]["Reembolso"] = 'N'  # opcional
        # datas["DatosServicio"]["ImporteReembolso"] = 'N' # para envios con reembolso
        datas["DatosServicio"]["TipoMercancia"] = 'ATV'  # opcional
        datas["DatosServicio"]["ValorDeclarado"] = 123.34
        datas["DatosServicio"]["Notificaciones"] = [1, 2, 'jsoler@centrologic.com']  # CanalNotificacion, TipoNotificacion, MailSMS
        # datas["DatosServicio"]["SeguroOpcional"]=  #opcional
        
        # Send the request
        try:
            client.set_options(soapheaders=auth)
            m = client.service.TransmEnvio(datas)
        except WebFault as e:
            print(e)
            raise
        
        print("TransmEnvio: {}".format(m))
    
    def __query_seur(self, meta, config):
        # Default config
        config = {
            'wspub': 'https://ws.seur.com/WSEcatalogoPublicos/servlet/XFireServlet/WSServiciosWebPublicos?wsdl',  # Pubic WSDL (cities & postal codes)$
            'wsprint': 'http://cit.seur.com/CIT-war/services/ImprimirECBWebService?wsdl',        # PrintService WSDL (print ticket)$
            'wsdetails': 'http://cit.seur.com/CIT-war/services/DetalleBultoPDFWebService?wsdl',  # Details WSDL (listado)$
            'wsexpedition': 'https://ws.seur.com/webseur/services/WSConsultaExpediciones?wsdl',  # Expedition WSDL (consulta expediciones)$
        }
        # Pickup WSDL (recogida)
        if self.real:
            config['wspickup'] = 'https://ws.seur.com/webseur/services/WSCrearRecogida?wsdl',
        else:
            config['wspickup'] = 'https://wspre.seur.com/webseur/services/WSCrearRecogida?wsdl',


class TransportBox(CodenerixModel):
    '''
    Box were to transport anything we will transport
    __unicode__ method should look at least like this:
    return u"{0}:{1}Lx{2}Wx{3}H-{4}".format(self.locator, self.length, self.width, self.height, self.weight)
    '''
    locator = models.PositiveIntegerField(_('Locator'), blank=False, null=False, validators=[MaxValueValidator(2821109907455)])  # 2821109907455 => codenerix::hex36 = 8 char
    transport = models.ForeignKey(TransportRequest, blank=False, null=True, default=None)
    
    class Meta:
        abstract = True
    
    def length(self):
        raise TransportError("Method length not defined!")

    def width(self):
        raise TransportError("Method width not defined!")

    def heigth(self):
        raise TransportError("Method heigth not defined!")

    def weight(self):
        raise TransportError("Method weight not defined!")

    def value(self):
        raise TransportError("Method value not defined!")

    def notes(self):
        raise TransportError("Method notes not defined!")


class TransportError(Exception):
    '''
    ERROR CODES
    1:  Unknown protocol (is it a new protocol?)
    2:  Wrong environment (environment from the payment and the system do not match)
    3:  Unknown platform (did you change your configuration?)
    '''
    pass
