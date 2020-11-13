EESchema Schematic File Version 4
EELAYER 30 0
EELAYER END
$Descr A4 11693 8268
encoding utf-8
Sheet 9 9
Title "LUNA: Right Side I/O"
Date "2020-05-20"
Rev "r0"
Comp "Great Scott Gadgets"
Comment1 "Katherine J. Temkin"
Comment2 ""
Comment3 "Licensed under the CERN-OHL-P v2"
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
$Comp
L fpgas_and_processors:ECP5-BGA256 IC1
U 5 1 5DF17723
P 2150 2000
F 0 "IC1" H 2120 208 50  0000 R CNN
F 1 "ECP5-BGA256" H 2120 118 50  0000 R CNN
F 2 "luna:lattice_cabga256" H -1050 5450 50  0001 L CNN
F 3 "" H -1500 6400 50  0001 L CNN
F 4 "FPGA - Field Programmable Gate Array ECP5; 12k LUTs; 1.1V" H -1500 6300 50  0001 L CNN "Description"
F 5 "Lattice" H -1450 7250 50  0001 L CNN "Manufacturer"
F 6 "LFE5U-12F-6BG256C" H -1450 7150 50  0001 L CNN "Part Number"
	5    2150 2000
	1    0    0    -1  
$EndComp
$Comp
L power:+3V3 #PWR086
U 1 1 5DF1CB59
P 2350 1600
F 0 "#PWR086" H 2350 1450 50  0001 C CNN
F 1 "+3V3" H 2364 1773 50  0000 C CNN
F 2 "" H 2350 1600 50  0001 C CNN
F 3 "" H 2350 1600 50  0001 C CNN
	1    2350 1600
	1    0    0    -1  
$EndComp
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
NoConn ~ 3150 2800
NoConn ~ 3150 2900
NoConn ~ 3150 3000
NoConn ~ 3150 3100
NoConn ~ 3150 3400
NoConn ~ 3150 3500
NoConn ~ 3150 3800
NoConn ~ 3150 3900
NoConn ~ 3150 4000
NoConn ~ 3150 4100
NoConn ~ 3150 4800
NoConn ~ 3150 5000
NoConn ~ 3150 5100
NoConn ~ 3150 5200
NoConn ~ 3150 5300
Wire Wire Line
	3150 2500 4100 2500
Wire Wire Line
	3150 2600 4100 2600
Wire Wire Line
	3150 2700 4100 2700
Wire Wire Line
	3300 2800 3300 3200
Wire Wire Line
	3300 3200 3150 3200
Wire Wire Line
	3300 2800 4100 2800
Wire Wire Line
	3400 2900 3400 3300
Wire Wire Line
	3400 3300 3150 3300
Wire Wire Line
	3400 2900 4100 2900
Wire Wire Line
	3150 4700 3950 4700
Text HLabel 3950 4700 2    50   Output ~ 0
UC_RX_FPGA_TX
Wire Wire Line
	3150 4500 3950 4500
Text HLabel 3950 4500 2    50   Input ~ 0
UC_TX_FPGA_RX
Wire Wire Line
	3150 5400 3950 5400
Wire Wire Line
	3150 4400 3950 4400
Text HLabel 3950 5400 2    50   Output ~ 0
DEBUG_SPI_CIPO
Text HLabel 3950 4600 2    50   Input ~ 0
DEBUG_SPI_CLK
Text HLabel 3950 4400 2    50   Input ~ 0
DEBUG_SPI_COPI
Text HLabel 3950 4900 2    50   Input ~ 0
DEBUG_SPI_CS
Wire Wire Line
	3150 4900 3950 4900
NoConn ~ 3150 5500
Wire Wire Line
	3150 4600 3950 4600
NoConn ~ 3150 3600
NoConn ~ 3150 4200
NoConn ~ 3150 3700
NoConn ~ 3150 4300
$EndSCHEMATC
