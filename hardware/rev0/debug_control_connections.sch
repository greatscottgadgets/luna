EESchema Schematic File Version 4
LIBS:luna_rev0-cache
EELAYER 30 0
EELAYER END
$Descr A4 11693 8268
encoding utf-8
Sheet 7 9
Title "LUNA: Debug and Control Connections"
Date "2019-10-20"
Rev "r0"
Comp "Great Scott Gadgets"
Comment1 "Katherine J. Temkin"
Comment2 ""
Comment3 "Licensed under the CERN OHL v1.2"
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
Wire Wire Line
	3150 2400 3600 2400
Wire Wire Line
	3150 2600 3600 2600
Wire Wire Line
	3150 2700 3600 2700
Wire Wire Line
	3150 3650 3600 3650
Wire Wire Line
	3150 3750 3600 3750
Wire Wire Line
	3150 4650 3600 4650
Wire Wire Line
	3150 4750 3600 4750
Text HLabel 3600 2600 2    50   Input ~ 0
DEBUG_SPI_UC_OUT
Text HLabel 3600 2700 2    50   Output ~ 0
DEBUG_SPI_UC_IN
Text HLabel 3600 2400 2    50   Input ~ 0
DEBUG_SPI_CLK
Text HLabel 3600 3650 2    50   Output ~ 0
ALLOW_POWER_VIA_TARGET
Text HLabel 3600 3750 2    50   Output ~ 0
SUPPLY_POWER_TO_TARGET
$Comp
L fpgas_and_processors:ECP5-BGA256 IC1
U 2 1 5DFF5299
P 2200 1950
F 0 "IC1" H 2170 508 50  0000 R CNN
F 1 "ECP5-BGA256" H 2170 418 50  0000 R CNN
F 2 "luna:lattice_cabga256" H -1000 5400 50  0001 L CNN
F 3 "" H -1450 6350 50  0001 L CNN
F 4 "FPGA - Field Programmable Gate Array ECP5; 12k LUTs; 1.1V" H -1450 6250 50  0001 L CNN "Description"
F 5 "1.7" H -1450 6600 50  0001 L CNN "Height"
F 6 "Lattice" H -1400 7200 50  0001 L CNN "Manufacturer_Name"
F 7 "LFE5U-12F-6BG256C" H -1400 7100 50  0001 L CNN "Manufacturer_Part_Number"
F 8 "842-LFE5U12F6BG256C" H -750 5800 50  0001 L CNN "Mouser Part Number"
F 9 "https://www.mouser.com/Search/Refine.aspx?Keyword=842-LFE5U12F6BG256C" H -1100 5650 50  0001 L CNN "Mouser Price/Stock"
	2    2200 1950
	1    0    0    -1  
$EndComp
Text HLabel 3600 4650 2    50   Input ~ 0
TARGET_OVERCURRENT
Text HLabel 3600 4750 2    50   Input ~ 0
CLKIN_60MHZ
NoConn ~ 3150 2500
NoConn ~ 3150 2800
NoConn ~ 3150 2900
NoConn ~ 3150 3000
NoConn ~ 3150 3100
NoConn ~ 3150 3200
NoConn ~ 3150 3300
NoConn ~ 3150 3400
NoConn ~ 3150 3500
NoConn ~ 3150 3850
NoConn ~ 3150 3950
NoConn ~ 3150 4050
NoConn ~ 3150 4150
NoConn ~ 3150 4250
NoConn ~ 3150 4350
NoConn ~ 3150 4450
NoConn ~ 3150 4550
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
$EndSCHEMATC
