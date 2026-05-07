"""Set of HLASM mnemonics that the parser treats as native S/360-style
instructions or assembler directives. Anything else encountered in the op
field is reported as a macro call so the agent can look it up in the catalog
or flag it as unknown."""

# z/Architecture / S/360 base instructions we expect to see in legacy ALCS
# code. Not exhaustive — only the ops that show up regularly in airline
# transaction code. Extend as you encounter more.
BASE_INSTRUCTIONS: frozenset[str] = frozenset(
    {
        # branch
        "B", "BR", "BC", "BCR", "BAL", "BALR", "BAS", "BASR", "BCT", "BCTR",
        "BE", "BNE", "BH", "BNH", "BL", "BNL", "BZ", "BNZ", "BM", "BNM",
        "BP", "BNP", "BO", "BNO", "BXH", "BXLE", "J", "JE", "JNE", "JH",
        "JL", "JNH", "JNL", "JZ", "JNZ",
        # load / store
        "L", "LA", "LH", "LM", "LR", "LTR", "LCR", "LNR", "LPR", "LH",
        "ICM", "STCM", "ST", "STH", "STM", "STC", "MVI", "MVC", "MVCL",
        "MVN", "MVZ", "MVO",
        # arithmetic
        "A", "AR", "AH", "AL", "ALR", "S", "SR", "SH", "SL", "SLR",
        "M", "MR", "MH", "D", "DR",
        # packed decimal
        "AP", "SP", "MP", "DP", "CP", "ZAP", "PACK", "UNPK", "ED", "EDMK",
        "SRP",
        # logical
        "N", "NR", "NC", "NI", "O", "OR", "OC", "OI", "X", "XR", "XC", "XI",
        # compare
        "C", "CR", "CH", "CL", "CLR", "CLC", "CLI", "CLM",
        # shift
        "SLA", "SRA", "SLL", "SRL", "SLDA", "SRDA", "SLDL", "SRDL",
        # control / misc
        "TM", "EX", "NOP", "NOPR", "SVC", "TS", "TR", "TRT",
    }
)

# Ops that take NO operands. Critical for parser correctness because HLASM
# does not syntactically separate operands from comments — without this set,
# the first word of a trailing comment gets misread as the operand. Extend
# with project-specific zero-operand macros (BACKC, EXITC are the common
# ALCS ones).
ZERO_OPERAND_OPS: frozenset[str] = frozenset(
    {
        "NOP", "NOPR",
        # ALCS / TPF macros that conventionally take no operands. Add new
        # entries only when you are confident — a wrongly-listed op silently
        # discards real operand text. (DEFRC and WAITC commonly take operands
        # at most sites, so they are not listed here.)
        "BACKC", "EXITC",
    }
)

# Assembler directives — same parser path, but flagged so the structural
# pass can act on them (CSECT/DSECT/USING/DC/DS/EQU/END drive the model).
DIRECTIVES: frozenset[str] = frozenset(
    {
        "CSECT", "DSECT", "RSECT", "START", "END", "EQU", "USING", "DROP",
        "DC", "DS", "ORG", "LTORG", "COPY", "PRINT", "EJECT", "SPACE",
        "TITLE", "PUSH", "POP", "ENTRY", "EXTRN", "WXTRN", "ALIAS",
        "AGO", "AIF", "ANOP", "MACRO", "MEND", "MEXIT", "MNOTE",
        "GBLA", "GBLB", "GBLC", "LCLA", "LCLB", "LCLC", "SETA", "SETB",
        "SETC", "ACTR", "AREAD",
    }
)
