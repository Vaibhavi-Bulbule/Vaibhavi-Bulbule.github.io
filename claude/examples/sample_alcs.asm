*--------------------------------------------------------------------*
* SAMPLE ALCS / TPF HLASM SOURCE - PNR FARE LOOKUP STUB
* Looks up a fare for a given origin/destination/booking class and
* returns the amount in EBCDIC packed decimal. Not real Sabre code -
* representative shapes only.
*--------------------------------------------------------------------*
FARELKUP CSECT
         ENTRC FARELKUP            ALCS entry point
         USING ECBPGM,R9           ECB addressability
         L     R2,EBROUT           load origin pointer
         L     R3,EBRDST           load destination pointer
         CLC   0(3,R2),0(R3)       same city pair?
         BE    SAMECITY            then return zero
*
         LA    R4,FAREKEY          build lookup key
         MVC   0(3,R4),0(R2)       origin
         MVC   3(3,R4),0(R3)       destination
         MVC   6(2,R4),EBRBKC      booking class
*
         FINDC FAREDB,KEY=FAREKEY,RC=FRC
         LTR   R15,R15             find ok?
         BNZ   NOTFOUND
*
         L     R5,FAREAMT          loaded fare amount (packed)
         BACKC                     return success, R5 holds amount
*
SAMECITY DS    0H
         SR    R5,R5
         BACKC
*
NOTFOUND DS    0H
         LA    R15,8               error code 8 = not found
         BACKC
*
FAREKEY  DS    CL8
FRC      DS    F
         LTORG
*
ECBPGM   DSECT
EBROUT   DS    A                   pointer to origin (3 chars)
EBRDST   DS    A                   pointer to destination (3 chars)
EBRBKC   DS    CL2                 booking class
FAREAMT  DS    PL5                 packed decimal fare
         END
