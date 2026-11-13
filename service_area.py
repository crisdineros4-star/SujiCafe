"""Delivery coverage: Los Baños, Bay, Santa Cruz, San Pablo and Calamba."""
import math
DELIVERY_CITY = 'Los Baños'
DELIVERY_BARANGAYS = ['Anos', 'Bagong Silang', 'Bambang', 'Batong Malake', 'Baybayin (Pob.)', 'Bayog', 'Lalakay', 'Maahas', 'Malinta', 'Mayondon', 'Putho Tuntungin', 'San Antonio', 'Tadlak', 'Timugan (Pob.)']
DELIVERY_COVERAGE = {'Los Baños': DELIVERY_BARANGAYS,
    'Bay': ['Bitin', 'Calo', 'Dila', 'Maitim', 'Masaya', 'Paciano Rizal', 'Puypuy', 'San Agustin (Pob.)', 'San Antonio', 'San Isidro', 'San Nicolas (Pob.)', 'Santa Cruz', 'Santo Domingo', 'Tagumpay', 'Tranca'],
    'Santa Cruz': ['Alipit', 'Bagumbayan', 'Barangay I (Pob.)', 'Barangay II (Pob.)', 'Barangay III (Pob.)', 'Barangay IV (Pob.)', 'Barangay V (Pob.)', 'Bubukal', 'Calios', 'Duhat', 'Gatid', 'Jasaan', 'Labuin', 'Malinao', 'Oogong', 'Pagsawitan', 'Palasan', 'Patimbao', 'San Jose', 'San Juan', 'San Pablo Norte', 'San Pablo Sur', 'Santisima Cruz', 'Santo Angel Central', 'Santo Angel Norte', 'Santo Angel Sur'],
    'San Pablo': ['Atisan', 'Bagong Bayan II-A (Pob.)', 'Bagong Pook VI-C (Pob.)', 'Barangay I-A (Pob.)', 'Barangay I-B (Pob.)', 'Barangay II-A (Pob.)', 'Barangay II-B (Pob.)', 'Barangay II-C (Pob.)', 'Barangay II-D (Pob.)', 'Barangay II-E (Pob.)', 'Barangay II-F (Pob.)', 'Barangay III-A (Pob.)', 'Barangay III-B (Pob.)', 'Barangay III-C (Pob.)', 'Barangay III-D (Pob.)', 'Barangay III-E (Pob.)', 'Barangay III-F (Pob.)', 'Barangay IV-A (Pob.)', 'Barangay IV-B (Pob.)', 'Barangay IV-C (Pob.)', 'Barangay V-A (Pob.)', 'Barangay V-B (Pob.)', 'Barangay V-C (Pob.)', 'Barangay V-D (Pob.)', 'Barangay VI-A (Pob.)', 'Barangay VI-B (Pob.)', 'Barangay VI-D (Pob.)', 'Barangay VI-E (Pob.)', 'Barangay VII-A (Pob.)', 'Barangay VII-B (Pob.)', 'Barangay VII-C (Pob.)', 'Barangay VII-D (Pob.)', 'Barangay VII-E (Pob.)', 'Bautista', 'Concepcion', 'Del Remedio', 'Dolores', 'San Antonio 1', 'San Antonio 2', 'San Bartolome', 'San Buenaventura', 'San Crispin', 'San Cristobal', 'San Diego', 'San Francisco', 'San Gabriel', 'San Gregorio', 'San Ignacio', 'San Isidro', 'San Joaquin', 'San Jose', 'San Juan', 'San Lorenzo', 'San Lucas 1', 'San Lucas 2', 'San Marcos', 'San Mateo', 'San Miguel', 'San Nicolas', 'San Pedro', 'San Rafael', 'San Roque', 'San Vicente', 'Santa Ana', 'Santa Catalina', 'Santa Cruz', 'Santa Elena', 'Santa Felomina', 'Santa Isabel', 'Santa Maria', 'Santa Maria Magdalena', 'Santa Monica', 'Santa Veronica', 'Santiago I', 'Santiago II', 'Santisimo Rosario', 'Santo Angel', 'Santo Cristo', 'Santo Niño', 'Soledad'],
    'Calamba': ['Bagong Kalsada', 'Banadero', 'Banlic', 'Barandal', 'Barangay 1 (Pob.)', 'Barangay 2 (Pob.)', 'Barangay 3 (Pob.)', 'Barangay 4 (Pob.)', 'Barangay 5 (Pob.)', 'Barangay 6 (Pob.)', 'Barangay 7 (Pob.)', 'Batino', 'Bubuyan', 'Bucal', 'Bunggo', 'Burol', 'Camaligan', 'Canlubang', 'Halang', 'Hornalan', 'Kay-Anlog', 'La Mesa', 'Laguerta', 'Lawa', 'Lecheria', 'Lingga', 'Looc', 'Mabato', 'Majada Labas', 'Makiling', 'Mapagong', 'Masili', 'Maunong', 'Mayapa', 'Milagrosa', 'Paciano Rizal', 'Palingon', 'Palo-Alto', 'Pansol', 'Parian', 'Prinza', 'Punta', 'Puting Lupa', 'Real', 'Saimsim', 'Sampiruhan', 'San Cristobal', 'San Jose', 'San Juan', 'Sirang Lupa', 'Sucol', 'Turbina', 'Ulango', 'Uwisan'],
}
DELIVERY_RADII_KM={'Los Baños':8,'Bay':15,'Santa Cruz':35,'San Pablo':30,'Calamba':30}
# Approximate municipality map centre, NOT verified café GPS coordinates.
AREA_LAT, AREA_LNG = 14.1667, 121.2333
PIN_RADIUS_KM = 8

def pin_allowed(lat,lng,city='Los Baños'):
    if not all(math.isfinite(v) for v in (lat,lng)):return False
    a,b=map(math.radians,(lat-AREA_LAT,lng-AREA_LNG))
    h=math.sin(a/2)**2+math.cos(math.radians(AREA_LAT))*math.cos(math.radians(lat))*math.sin(b/2)**2
    radius=max(DELIVERY_RADII_KM.values()) if city is None else DELIVERY_RADII_KM.get(canonical_city(city),PIN_RADIUS_KM)
    return h<=math.sin(radius/12742)**2

def canonical_city(value):
    raw=str(value or '').strip().casefold()
    aliases={'los baños':'Los Baños','los banos':'Los Baños','bay':'Bay','calamba':'Calamba','city of calamba':'Calamba','santa cruz':'Santa Cruz','sta cruz':'Santa Cruz','sta. cruz':'Santa Cruz','san pablo':'San Pablo','city of san pablo':'San Pablo','san pablo city':'San Pablo'}
    return aliases.get(raw,'')

def address_allowed(values):
    city=canonical_city(values.get('city',''))
    return (city in DELIVERY_COVERAGE
        and values.get('province','').strip().casefold()=='laguna'
        and values.get('region','').strip().casefold() in {'calabarzon','calabarzon (region iv-a)','region iv-a','region iv a'}
        and values.get('barangay','').strip().casefold() in {b.casefold() for b in DELIVERY_COVERAGE.get(city,[])})
