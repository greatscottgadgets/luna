EESchema Schematic File Version 4
EELAYER 30 0
EELAYER END
$Descr A4 11693 8268
encoding utf-8
Sheet 9 9
Title "LUNA: Debug and Control Connections"
Date "2020-12-20"
Rev "r0"
Comp "Great Scott Gadgets"
Comment1 "Katherine J. Temkin"
Comment2 ""
Comment3 "Licensed under the CERN-OHL-P v2"
Comment4 ""
$EndDescr
Wire Wire Line
	2400 1750 2400 1650
Wire Wire Line
	2400 1650 2450 1650
Wire Wire Line
	2500 1650 2500 1750
Wire Wire Line
	2450 1650 2450 1500
Connection ~ 2450 1650
Wire Wire Line
	2450 1650 2500 1650
Text HLabel 3700 4750 2    50   Input ~ 0
CLKIN_60MHZ
NoConn ~ 3150 2500
NoConn ~ 3150 2800
NoConn ~ 3150 2900
NoConn ~ 3150 3000
NoConn ~ 3150 3200
NoConn ~ 3150 3300
NoConn ~ 3150 3400
NoConn ~ 3150 3850
NoConn ~ 3150 3950
NoConn ~ 3150 4250
NoConn ~ 3150 4350
$Comp
L power:+3V3 #PWR0105
U 1 1 5E3ECE52
P 2450 1500
F 0 "#PWR0105" H 2450 1350 50  0001 C CNN
F 1 "+3V3" H 2464 1673 50  0000 C CNN
F 2 "" H 2450 1500 50  0001 C CNN
F 3 "" H 2450 1500 50  0001 C CNN
	1    2450 1500
	1    0    0    -1  
$EndComp
Wire Wire Line
	3150 4750 3700 4750
$Comp
L Device:R_Pack04 RN?
U 1 1 61658D8E
P 4850 3200
AR Path="/61658D8E" Ref="RN?"  Part="1" 
AR Path="/5DF88884/61658D8E" Ref="RN1"  Part="1" 
F 0 "RN1" V 4433 3200 50  0000 C CNN
F 1 "R_Pack04" V 4524 3200 50  0000 C CNN
F 2 "Resistor_SMD:R_Array_Convex_4x0402" V 5125 3200 50  0001 C CNN
F 3 "~" H 4850 3200 50  0001 C CNN
F 4 "RES ARRAY 4 RES 33 OHM 0804" H 4850 3200 50  0001 C CNN "Description"
F 5 "Yageo" H 4850 3200 50  0001 C CNN "Manufacturer"
F 6 "YC124-JR-0733RL" H 4850 3200 50  0001 C CNN "Part Number"
	1    4850 3200
	0    1    1    0   
$EndComp
$Comp
L Device:R_Pack04 RN?
U 1 1 61658D97
P 4850 3850
AR Path="/61658D97" Ref="RN?"  Part="1" 
AR Path="/5DF88884/61658D97" Ref="RN2"  Part="1" 
F 0 "RN2" V 4433 3850 50  0000 C CNN
F 1 "R_Pack04" V 4524 3850 50  0000 C CNN
F 2 "Resistor_SMD:R_Array_Convex_4x0402" V 5125 3850 50  0001 C CNN
F 3 "~" H 4850 3850 50  0001 C CNN
F 4 "RES ARRAY 4 RES 33 OHM 0804" H 4850 3850 50  0001 C CNN "Description"
F 5 "Yageo" H 4850 3850 50  0001 C CNN "Manufacturer"
F 6 "YC124-JR-0733RL" H 4850 3850 50  0001 C CNN "Part Number"
	1    4850 3850
	0    1    1    0   
$EndComp
Text HLabel 5150 3850 2    50   BiDi ~ 0
PMOD6
Text HLabel 5150 3950 2    50   BiDi ~ 0
PMOD7
Text HLabel 5150 3000 2    50   BiDi ~ 0
PMOD0
Text HLabel 5150 3100 2    50   BiDi ~ 0
PMOD1
Text HLabel 5150 3300 2    50   BiDi ~ 0
PMOD2
Text HLabel 5150 3750 2    50   BiDi ~ 0
PMOD3
Text HLabel 5150 3200 2    50   BiDi ~ 0
PMOD4
Text HLabel 5150 3650 2    50   BiDi ~ 0
PMOD5
Wire Wire Line
	4550 3000 4650 3000
NoConn ~ 3150 3100
NoConn ~ 3150 2400
Wire Wire Line
	5050 3950 5150 3950
Wire Wire Line
	5050 3850 5150 3850
Wire Wire Line
	5050 3750 5150 3750
Wire Wire Line
	5050 3650 5150 3650
Wire Wire Line
	5050 3300 5150 3300
Wire Wire Line
	5050 3200 5150 3200
Wire Wire Line
	5050 3100 5150 3100
Wire Wire Line
	5050 3000 5150 3000
NoConn ~ 3150 4650
$Comp
L fpgas_and_processors:ECP5-BGA256 IC1
U 2 1 5DFF5299
P 2200 1950
F 0 "IC1" H 2170 508 50  0000 R CNN
F 1 "ECP5-BGA256" H 2170 418 50  0000 R CNN
F 2 "luna:lattice_cabga256" H -1000 5400 50  0001 L CNN
F 3 "" H -1450 6350 50  0001 L CNN
F 4 "FPGA - Field Programmable Gate Array ECP5; 12k LUTs; 1.1V" H -1450 6250 50  0001 L CNN "Description"
F 5 "Lattice" H -1400 7200 50  0001 L CNN "Manufacturer"
F 6 "LFE5U-12F-6BG256C" H -1400 7100 50  0001 L CNN "Part Number"
	2    2200 1950
	1    0    0    -1  
$EndComp
NoConn ~ 3150 3500
Wire Wire Line
	3150 2600 4550 2600
Wire Wire Line
	4550 2600 4550 3000
Wire Wire Line
	4650 3100 4450 3100
Wire Wire Line
	4450 3100 4450 2700
Wire Wire Line
	4450 2700 3150 2700
Wire Wire Line
	3150 4050 4150 4050
Wire Wire Line
	4150 4050 4150 3200
Wire Wire Line
	4150 3200 4650 3200
Wire Wire Line
	3150 3650 3950 3650
Wire Wire Line
	3950 3650 3950 3300
Wire Wire Line
	3950 3300 4650 3300
Wire Wire Line
	3150 4150 4250 4150
Wire Wire Line
	4250 4150 4250 3650
Wire Wire Line
	4250 3650 4650 3650
Wire Wire Line
	3150 3750 4650 3750
Wire Wire Line
	3150 4550 4550 4550
Wire Wire Line
	4550 4550 4550 3950
Wire Wire Line
	4550 3950 4650 3950
Wire Wire Line
	4650 3850 4450 3850
Wire Wire Line
	4450 3850 4450 4450
Wire Wire Line
	4450 4450 3150 4450
$EndSCHEMATC
