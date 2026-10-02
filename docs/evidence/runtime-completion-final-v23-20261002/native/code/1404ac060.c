
/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */

void FUN_1404ac060(longlong *param_1,ulonglong param_2)

{
  ulonglong uVar1;
  bool bVar2;
  longlong lVar3;
  longlong lVar4;
  longlong lVar5;
  ulonglong uVar6;
  ulonglong uVar7;
  float fVar8;
  undefined1 auStack_68 [32];
  float fStack_48;
  float fStack_44;
  float fStack_40;
  float fStack_3c;
  ulonglong uStack_38;
  
  uStack_38 = _DAT_1428792c0 ^ (ulonglong)auStack_68;
  uVar1 = param_1[0x2e2];
  if (uVar1 < param_2) {
    uVar6 = 1;
    if (1 < param_2) {
      uVar6 = param_2;
    }
    uVar7 = param_1[0x2e3];
    if (uVar6 < (ulonglong)param_1[0x2e3]) {
      uVar7 = uVar6;
    }
    param_1[0x302] = uVar7 - uVar1;
    (**(code **)(*param_1 + 0x680))(param_1,(float)uVar7 / (float)uVar1,0);
    fVar8 = (float)uVar7 / (float)(ulonglong)param_1[0x2e3];
    (**(code **)(*param_1 + 0x328))
              (param_1,SQRT(fVar8) *
                       (*(float *)(param_1 + 0x2e7) - *(float *)((longlong)param_1 + 0x1734)) +
                       *(float *)((longlong)param_1 + 0x1734),0);
    if ((((char)param_1[0x2e5] != '\0') && (*(uint *)(param_1 + 0x59) != 0)) &&
       (lVar3 = param_1[0x58], lVar3 != (ulonglong)*(uint *)(param_1 + 0x59) + lVar3)) {
      do {
        if (((*(byte *)(lVar3 + 0x45) & 1) == 0) &&
           (lVar4 = **(longlong **)(lVar3 + 0x30), lVar4 != 0)) {
          lVar5 = *(longlong *)(lVar4 + 8);
          if ((int)(*(uint *)(lVar5 + 8) | _DAT_1429cf898) < 0) {
            do {
              if (lVar5 == 0x1429cf890) {
                bVar2 = true;
                goto LAB_1404ac494;
              }
              lVar5 = *(longlong *)(lVar5 + 0x18);
            } while (lVar5 != 0);
            bVar2 = false;
          }
          else {
            bVar2 = *(uint *)(lVar5 + 8) - _DAT_1429cf898 <= _DAT_1429cf89c;
          }
LAB_1404ac494:
          if (bVar2) {
            wf_140ef69d0(lVar4,fVar8);
          }
        }
        lVar3 = lVar3 + 0x48;
      } while (lVar3 != (ulonglong)*(uint *)(param_1 + 0x59) + param_1[0x58]);
    }
    fVar8 = (*(float *)(param_1 + 0x2e8) - *(float *)((longlong)param_1 + 0x173c)) * fVar8 +
            *(float *)((longlong)param_1 + 0x173c);
    *(float *)((longlong)param_1 + 0x63c) = fVar8;
    if (((*(byte *)((longlong)param_1 + 0x185d) & 1) == 0) &&
       (lVar3 = *(longlong *)param_1[0x309], lVar3 != 0)) {
      lVar4 = *(longlong *)(lVar3 + 8);
      if ((int)(*(uint *)(lVar4 + 8) | _DAT_1428c82f8) < 0) {
        do {
          if (lVar4 == 0x1428c82f0) {
            bVar2 = true;
            goto LAB_1404ac538;
          }
          lVar4 = *(longlong *)(lVar4 + 0x18);
        } while (lVar4 != 0);
        bVar2 = false;
      }
      else {
        bVar2 = *(uint *)(lVar4 + 8) - _DAT_1428c82f8 <= _DAT_1428c82fc;
      }
LAB_1404ac538:
      if (bVar2) {
        fStack_48 = fVar8;
        fStack_44 = fVar8;
        fStack_40 = fVar8;
        fStack_3c = fVar8;
        FUN_141782fd0(lVar3,&fStack_48);
      }
    }
    param_1[0x2e2] = uVar7;
  }
  else {
    lVar3 = FUN_140a92310(0x14288b150,3);
    FUN_140a26560(lVar3,&UNK_1423c8950,0x22);
    FUN_1418722f0(lVar3 + 0x38,param_2);
    FUN_140a26560(lVar3,&UNK_1423c8978,0x1d);
    FUN_1418722f0(lVar3 + 0x38,param_1[0x2e2]);
    FUN_140a26560(lVar3,&UNK_1420059a4,1);
    lVar3 = FUN_140a92310(0x14288b150,3);
    FUN_140a26560(lVar3,&UNK_1423c8998,0x20);
    FUN_14161ee80(lVar3 + 0x38,*(undefined1 *)((longlong)param_1 + 0x172a));
    FUN_140a26560(lVar3,&UNK_1420059a4,1);
    lVar3 = FUN_140a92310(0x14288b150,3);
    FUN_140a26560(lVar3,&UNK_1423c89c0,0xb);
    FUN_14161ee80(lVar3 + 0x38,(*(byte *)((longlong)param_1 + 0x21) & 7) != 0);
    FUN_140a26560(lVar3,&UNK_1420059a4,1);
    lVar3 = FUN_140a92310(0x14288b150,3);
    FUN_140a26560(lVar3,&UNK_1423c89d0,0x1d);
    FUN_14161ee80(lVar3 + 0x38,(char)param_1[0x1ac]);
    FUN_140a26560(lVar3,&UNK_1420059a4,1);
    lVar3 = FUN_140a92310(0x14288b150,3);
    FUN_140a26560(lVar3,&UNK_1423c89f0,0x1a);
    FUN_14161ee80(lVar3 + 0x38,(char)param_1[0x1f1]);
    FUN_140a26560(lVar3,&UNK_1420059a4,1);
    if (*(longlong *)param_1[0xe7] != 0) {
      lVar4 = FUN_140a92310(0x14288b150,3);
      FUN_140a26560(lVar4,&UNK_1423c8a10,0xb);
      lVar3 = *(longlong *)param_1[0xe7];
      fStack_40 = *(float *)(lVar3 + 0x18);
      fStack_44 = *(float *)(*(longlong *)(lVar3 + 8) + 0x2c);
      fStack_48 = *(float *)(lVar3 + 0x1c);
      FUN_14111faa0(lVar4 + 0x38,&fStack_48);
      FUN_140a26560(lVar4,&UNK_1420059a4,1);
    }
    if (*(longlong *)param_1[0xe1] != 0) {
      lVar4 = FUN_140a92310(0x14288b150,3);
      FUN_140a26560(lVar4,&UNK_1423c8a20,0x10);
      lVar3 = *(longlong *)param_1[0xe7];
      fStack_40 = *(float *)(lVar3 + 0x18);
      fStack_44 = *(float *)(*(longlong *)(lVar3 + 8) + 0x2c);
      fStack_48 = *(float *)(lVar3 + 0x1c);
      FUN_14111faa0(lVar4 + 0x38,&fStack_48);
      FUN_140a26560(lVar4,&UNK_1420059a4,1);
    }
  }
  FUN_141bf6fc0(uStack_38 ^ (ulonglong)auStack_68);
  return;
}

