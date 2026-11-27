/*
 * SC-1 co-processor register map (I2C slave 0x2A on the main-board bus).
 *
 * All multi-byte values are little-endian. Read: write the start register,
 * then a repeated-start read of up to 16 bytes (the pointer auto-increments).
 * Write: start register followed by data bytes.
 *
 * This file is shared with the node firmware (Firmware/src/sc1.c): keep both
 * copies identical.
 */
#ifndef SC1_REGS_H
#define SC1_REGS_H

#define SC1_I2C_ADDR        0x2A
#define SC1_ID_VALUE        0x5C
#define SC1_FW_VERSION      0x01
#define SC1_REG_COUNT       0x40

/* ---- identity, status, command ---- */
#define SC1_REG_ID          0x00  /* u8  0x5C */
#define SC1_REG_FW          0x01  /* u8  firmware version */
#define SC1_REG_STATUS      0x02  /* u8  flags below; cleared with SC1_CMD_CLEAR */
#define SC1_REG_CMD         0x03  /* u8  write-only command */
#define SC1_REG_UPTIME      0x04  /* u32 seconds since power-up */

/* ---- measurements (read-only) ---- */
#define SC1_REG_VBAT_MV     0x10  /* u16 battery voltage, mV */
#define SC1_REG_IBAT        0x12  /* s16 battery current, 0.1 mA, + = discharging */
#define SC1_REG_SOC         0x14  /* u8  state of charge, % */
#define SC1_REG_TEMP_CELL   0x16  /* s16 cell temperature, 0.01 degC (0x8000 = no probe) */
#define SC1_REG_TEMP_SOIL   0x18  /* s16 soil temperature, 0.01 degC (0x8000 = no probe) */
#define SC1_REG_SOIL_RAW    0x1A  /* u16 soil probe, 12-bit ADC counts */
#define SC1_REG_SOIL_PCT    0x1C  /* u8  soil moisture, % (0xFF = no probe) */
#define SC1_REG_BORER_IDX   0x1D  /* u8  borer activity index 0-100 (last listen) */
#define SC1_REG_BORER_CPM   0x1E  /* u16 impulsive clicks per minute (last listen) */
#define SC1_REG_RAIN_1H     0x20  /* u16 rain gauge tips, last 60 min (0.2 mm each) */
#define SC1_REG_RAIN_24H    0x22  /* u16 tips, last 24 h */
#define SC1_REG_RAIN_3D     0x24  /* u16 tips, last 3 days */
#define SC1_REG_RAIN_5D     0x26  /* u16 tips, last 5 days */
#define SC1_REG_RAIN_7D     0x28  /* u16 tips, last 7 days */
#define SC1_REG_RAIN_15D    0x2A  /* u16 tips, last 15 days */
#define SC1_REG_USED_MAH    0x2C  /* s32 charge drawn since last full, 0.01 mAh */

/* ---- configuration (read/write, saved with SC1_CMD_SAVE) ---- */
#define SC1_REG_CAPACITY    0x30  /* u16 cell capacity, mAh (1000) */
#define SC1_REG_BATT_PERIOD 0x32  /* u16 battery sample period, s (60) */
#define SC1_REG_FIELD_PERIOD 0x34 /* u16 soil + NTC period, s (1800) */
#define SC1_REG_SOIL_DRY    0x36  /* u16 soil raw in dry air (2730) */
#define SC1_REG_SOIL_WET    0x38  /* u16 soil raw in water (1240) */
#define SC1_REG_RAIN_ALERT  0x3A  /* u16 tips in 60 min that raise RAIN_ALERT (50 = 10 mm/h) */
#define SC1_REG_LOW_BATT    0x3C  /* u8  SOC % that raises LOW_BATT (15) */
#define SC1_REG_BORER_ALERT 0x3D  /* u8  borer index that raises BORER_ALERT (50) */
#define SC1_REG_LISTEN_S    0x3E  /* u8  borer listen window, s (20) */
#define SC1_REG_WAKE_MASK   0x3F  /* u8  STATUS bits that pulse WAKE (0x0E) */
#define SC1_CONFIG_FIRST    SC1_REG_CAPACITY

/* STATUS bits */
#define SC1_ST_RAIN_TIP     0x01  /* at least one tip since last clear */
#define SC1_ST_RAIN_ALERT   0x02  /* rain in last 60 min >= RAIN_ALERT */
#define SC1_ST_LOW_BATT     0x04  /* SOC <= LOW_BATT or VBAT < 3.0 V */
#define SC1_ST_BORER_ALERT  0x08  /* last listen index >= BORER_ALERT */
#define SC1_ST_INA_FAULT    0x10  /* INA219 did not answer */
#define SC1_ST_LISTENING    0x20  /* borer listen window running */
#define SC1_ST_NEW_DATA     0x40  /* measurements updated since last clear */
/* Bits cleared by SC1_CMD_CLEAR. LOW_BATT is a level: it follows each battery sample,
 * and WAKE pulses only when it is first raised. */
#define SC1_ST_EVENTS       (SC1_ST_RAIN_TIP | SC1_ST_RAIN_ALERT | SC1_ST_BORER_ALERT | \
			     SC1_ST_NEW_DATA)

/* Commands (write to SC1_REG_CMD) */
#define SC1_CMD_MEASURE     0x01  /* sample battery, soil and NTCs now */
#define SC1_CMD_CLEAR       0x02  /* clear STATUS event bits */
#define SC1_CMD_BATT_FULL   0x03  /* the cell is full now: SOC = 100 % */
#define SC1_CMD_LISTEN      0x10  /* start a borer listen window */
#define SC1_CMD_SAVE        0xA5  /* save configuration to EEPROM */
#define SC1_CMD_DEFAULTS    0xD0  /* restore default configuration */

#define SC1_TEMP_INVALID    ((int16_t)0x8000)

#endif
