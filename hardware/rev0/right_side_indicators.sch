EESchema Schematic File Version 4
LIBS:luna_rev0-cache
EELAYER 29 0
EELAYER END
$Descr A4 11693 8268
encoding utf-8
Sheet 7 9
Title "LUNA: Right Side I/O"
Date "2019-10-20"
Rev "r0"
Comp "Great Scott Gadgets"
Comment1 "Katherine J. Temkin"
Comment2 ""
Comment3 "Licensed under the CERN OHL v1.2"
Comment4 ""
$EndDescr
Wire Wire Line
	2300 1800 2300 1750
Wire Wire Line
	2300 1750 2350 1750
Wire Wire Line
	2400 1750 2400 1800
Connection ~ 2350 1750
Wire Wire Line
	2350 1750 2400 1750
Wire Wire Line
	2350 1600 2350 1750
Wire Wire Line
	3500 2500 3500 2600
Wire Wire Line
	3500 2600 3150 2600
Wire Wire Line
	3800 3700 3150 3700
Wire Wire Line
	3600 2600 3600 3200
Wire Wire Line
	3600 3200 3150 3200
Wire Wire Line
	3700 2700 3700 3600
Wire Wire Line
	3700 3600 3150 3600
Wire Wire Line
	3800 2800 3800 3700
Wire Wire Line
	3150 4200 3950 4200
Wire Wire Line
	3950 4200 3950 2900
$Comp
L fpgas_and_processors:ECP5-BGA256 IC?
U 5 1 5DF17723
P 2150 2000
F 0 "IC?" H 2120 208 50  0000 R CNN
F 1 "ECP5-BGA256" H 2120 118 50  0000 R CNN
F 2 "BGA256C80P16X16_1400X1400X170" H -1050 5450 50  0001 L CNN
F 3 "" H -1500 6400 50  0001 L CNN
F 4 "FPGA - Field Programmable Gate Array ECP5; 12k LUTs; 1.1V" H -1500 6300 50  0001 L CNN "Description"
F 5 "1.7" H -1500 6650 50  0001 L CNN "Height"
F 6 "Lattice" H -1450 7250 50  0001 L CNN "Manufacturer_Name"
F 7 "LFE5U-12F-6BG256C" H -1450 7150 50  0001 L CNN "Manufacturer_Part_Number"
F 8 "842-LFE5U12F6BG256C" H -800 5850 50  0001 L CNN "Mouser Part Number"
F 9 "https://www.mouser.com/Search/Refine.aspx?Keyword=842-LFE5U12F6BG256C" H -1150 5700 50  0001 L CNN "Mouser Price/Stock"
	5    2150 2000
	1    0    0    -1  
$EndComp
$Comp
L power:+3V3 #PWR?
U 1 1 5DF1CB59
P 2350 1600
F 0 "#PWR?" H 2350 1450 50  0001 C CNN
F 1 "+3V3" H 2364 1773 50  0000 C CNN
F 2 "" H 2350 1600 50  0001 C CNN
F 3 "" H 2350 1600 50  0001 C CNN
	1    2350 1600
	1    0    0    -1  
$EndComp
Wire Wire Line
	3950 2900 4100 2900
Wire Wire Line
	4100 2800 3800 2800
Wire Wire Line
	4100 2700 3700 2700
Wire Wire Line
	4100 2600 3600 2600
Wire Wire Line
	4100 2500 3500 2500
Wire Wire Line
	4100 2400 3150 2400
Text HLabel 4100 2400 2    50   Output ~ 0
D5
Text HLabel 4100 2500 2    50   Output ~ 0
D4
Text HLabel 4100 2600 2    50   Output ~ 0
D3
Text HLabel 4100 2700 2    50   Output ~ 0
D2
Text HLabel 4100 2800 2    50   Output ~ 0
D1
Text HLabel 4100 2900 2    50   Output ~ 0
D0
$EndSCHEMATC
