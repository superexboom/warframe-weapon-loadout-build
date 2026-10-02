
/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */

void FUN_1415a16b0(longlong *param_1,float param_2)

{
  int *piVar1;
  bool bVar2;
  char cVar3;
  undefined4 uVar4;
  uint uVar5;
  longlong *plVar6;
  longlong *plVar7;
  longlong lVar8;
  float *pfVar9;
  longlong lVar10;
  ulonglong uVar11;
  longlong lVar12;
  ulonglong uVar13;
  int iVar14;
  int iVar15;
  float fVar16;
  float extraout_XMM0_Da;
  float fVar17;
  float fVar19;
  float fVar20;
  float fVar21;
  undefined1 auVar18 [16];
  undefined1 auVar22 [12];
  undefined1 auVar23 [16];
  
  lVar12 = *(longlong *)((longlong *)param_1[8])[0x1f];
  plVar6 = (longlong *)(**(code **)(*(longlong *)param_1[8] + 0x9f8))();
  plVar7 = (longlong *)(**(code **)(*plVar6 + 0x930))(plVar6);
  plVar7 = (longlong *)(**(code **)(*plVar7 + 0x5b0))(plVar7);
  fVar17 = _DAT_142007114;
  if (plVar7 == (longlong *)0x0) {
    lVar8 = 0;
LAB_1415a17ef:
    if (*(longlong *)param_1[0x46] != 0) {
      plVar7 = (longlong *)(**(code **)(*plVar6 + 0x930))(plVar6);
      pfVar9 = (float *)(**(code **)(*plVar7 + 0x5a0))(plVar7);
      auVar23._0_4_ = *pfVar9 - *(float *)(lVar12 + 0x70);
      auVar18._0_4_ = pfVar9[1] - *(float *)(lVar12 + 0x74);
      fVar20 = pfVar9[2] - *(float *)(lVar12 + 0x78);
      lVar10 = *(longlong *)param_1[0x46];
      fVar16 = *(float *)(lVar10 + 0x70) - *(float *)(lVar12 + 0x70);
      fVar19 = *(float *)(lVar10 + 0x74) - *(float *)(lVar12 + 0x74);
      fVar21 = *(float *)(lVar10 + 0x78) - *(float *)(lVar12 + 0x78);
      if ((lVar8 == 0) ||
         ((fVar16 * fVar16 + fVar19 * fVar19 + fVar21 * fVar21) -
          *(float *)((longlong)param_1 + 0x244) * *(float *)((longlong)param_1 + 0x244) <=
          auVar23._0_4_ * auVar23._0_4_ + auVar18._0_4_ * auVar18._0_4_ + fVar20 * fVar20)) {
        lVar10 = (**(code **)(*plVar6 + 0x760))(plVar6);
        lVar8 = *(longlong *)param_1[0x46];
        auVar22._0_4_ = *(float *)(lVar8 + 0x70) - *(float *)(lVar12 + 0x70);
        auVar22._4_4_ = *(float *)(lVar8 + 0x74) - *(float *)(lVar12 + 0x74);
        auVar22._8_4_ = *(float *)(lVar8 + 0x78) - *(float *)(lVar12 + 0x78);
        auVar23._0_4_ =
             SQRT(auVar22._0_4_ * auVar22._0_4_ + auVar22._4_4_ * auVar22._4_4_ +
                  auVar22._8_4_ * auVar22._8_4_);
        if (auVar23._0_4_ <= _DAT_142008014) {
          auVar23._0_4_ = (float)(~_DAT_142011220 & (uint)auVar22._0_4_);
          if ((float)(~_DAT_142011220 & (uint)auVar22._0_4_) <=
              (float)(~_UNK_142011224 & (uint)auVar22._4_4_)) {
            auVar23._0_4_ = (float)(~_UNK_142011224 & (uint)auVar22._4_4_);
          }
          if (auVar23._0_4_ <= (float)(~_UNK_142011228 & (uint)auVar22._8_4_)) {
            auVar23._0_4_ = (float)(~_UNK_142011228 & (uint)auVar22._8_4_);
          }
          if (0.0 < auVar23._0_4_) {
            auVar23._0_4_ = fVar17 / auVar23._0_4_;
            fVar16 = auVar23._0_4_ * auVar22._0_4_;
            auVar18._0_4_ = auVar23._0_4_ * auVar22._4_4_;
            auVar22._4_4_ = auVar18._0_4_;
            auVar22._0_4_ = fVar16;
            auVar23._0_4_ = auVar23._0_4_ * auVar22._8_4_;
            auVar22._8_4_ = auVar23._0_4_;
            fVar19 = SQRT(fVar16 * fVar16 + auVar18._0_4_ * auVar18._0_4_ +
                          auVar23._0_4_ * auVar23._0_4_);
            if (_DAT_142008014 < fVar19) {
              fVar19 = fVar17 / fVar19;
              auVar22._0_4_ = fVar19 * fVar16;
              auVar22._4_4_ = fVar19 * auVar18._0_4_;
              auVar22._8_4_ = fVar19 * auVar23._0_4_;
            }
          }
        }
        else {
          auVar23._0_4_ = fVar17 / auVar23._0_4_;
          auVar22._0_4_ = auVar22._0_4_ * auVar23._0_4_;
          auVar22._4_4_ = auVar22._4_4_ * auVar23._0_4_;
          auVar22._8_4_ = auVar22._8_4_ * auVar23._0_4_;
        }
        auVar23._0_4_ = *(float *)(lVar10 + 0x20);
        fVar16 = *(float *)(lVar10 + 0x24);
        auVar18._0_4_ = *(float *)(lVar10 + 0x28);
        fVar19 = (float)FUN_141c1ee60(*(float *)(param_1 + 0x48) * _DAT_1420126f0);
        if (fVar19 < auVar22._0_4_ * auVar23._0_4_ + auVar22._4_4_ * fVar16 +
                     auVar22._8_4_ * auVar18._0_4_) goto LAB_1415a1976;
      }
    }
    fVar17 = *(float *)(param_1 + 0x2c) - param_2 * *(float *)(param_1 + 0x47);
    if (fVar17 <= 0.0) {
      fVar17 = 0.0;
    }
    *(float *)(param_1 + 0x2c) = fVar17;
  }
  else {
    lVar8 = (**(code **)(*plVar7 + 0x2a8))(plVar7);
    if (lVar8 == 0) goto LAB_1415a17ef;
    lVar10 = *(longlong *)(lVar8 + 8);
    if ((int)(_DAT_1428b53d8 | *(uint *)(lVar10 + 8)) < 0) {
      do {
        if (lVar10 == 0x1428b53d0) {
          bVar2 = true;
          goto LAB_1415a177c;
        }
        lVar10 = *(longlong *)(lVar10 + 0x18);
      } while (lVar10 != 0);
      bVar2 = false;
    }
    else {
      bVar2 = *(uint *)(lVar10 + 8) - _DAT_1428b53d8 <= _DAT_1428b53dc;
    }
LAB_1415a177c:
    if ((!bVar2) || (*(int *)(lVar8 + 0x688) == (int)plVar6[0xd1])) goto LAB_1415a17ef;
    if (*(longlong *)param_1[0x46] != lVar8) {
      auVar23._0_4_ = *(float *)(param_1 + 0x2c) - *(float *)((longlong)param_1 + 0x23c);
      if (auVar23._0_4_ <= 0.0) {
        auVar23._0_4_ = 0.0;
      }
      *(float *)(param_1 + 0x2c) = auVar23._0_4_;
      plVar6 = *(longlong **)(lVar8 + 0x10);
      if ((longlong *)param_1[0x46] != plVar6) {
        *(int *)(plVar6 + 1) = (int)plVar6[1] + 1;
        piVar1 = (int *)(param_1[0x46] + 8);
        *piVar1 = *piVar1 + -1;
        if (*piVar1 == 0) {
          func_0x000141491930();
        }
        param_1[0x46] = (longlong)plVar6;
      }
    }
LAB_1415a1976:
    auVar23._0_4_ = *(float *)(param_1 + 0x2c);
    auVar18._0_4_ = (float)(**(code **)(*param_1 + 0x2c0))(param_1);
    fVar16 = param_2 + *(float *)(param_1 + 0x2c);
    if (auVar18._0_4_ <= param_2 + *(float *)(param_1 + 0x2c)) {
      fVar16 = auVar18._0_4_;
    }
    *(float *)(param_1 + 0x2c) = fVar16;
    fVar16 = (float)(**(code **)(*param_1 + 0x2b0))(param_1);
    if ((char)param_1[0x30] == '\0') {
      fVar17 = (*(float *)(param_1 + 0x2e) - fVar17) * fVar16 + fVar17;
    }
    else {
      if (*(char *)((longlong)param_1 + 0x1a4) != '\0') {
        uVar11 = (**(code **)(*(longlong *)param_1[8] + 0x2f8))();
        fVar20 = (float)uVar11;
        auVar18._0_4_ = *(float *)(param_1 + 0x34);
        fVar19 = fVar20;
        if ((0.0 < auVar18._0_4_) && (fVar19 = auVar18._0_4_, fVar20 <= auVar18._0_4_)) {
          fVar19 = fVar20;
        }
        uVar4 = (**(code **)(*param_1 + 0x2c0))(param_1);
        auVar18._0_4_ = fVar17 / (extraout_XMM0_Da / fVar19);
        auVar23._0_4_ = auVar18._0_4_ * auVar23._0_4_;
        iVar14 = (int)auVar23._0_4_;
        if ((iVar14 != -0x80000000) && ((float)iVar14 != auVar23._0_4_)) {
          auVar23._4_4_ = auVar23._0_4_;
          auVar23._8_8_ = 0;
          uVar5 = movmskps(uVar4,auVar23);
          auVar23._0_4_ = (float)(int)(iVar14 + (uVar5 & 1 ^ 1));
        }
        auVar18._0_4_ = auVar18._0_4_ * *(float *)(param_1 + 0x2c);
        iVar14 = 1;
        if (1 < (int)auVar23._0_4_) {
          iVar14 = (int)auVar23._0_4_;
        }
        iVar15 = (int)auVar18._0_4_;
        if ((iVar15 != -0x80000000) && ((float)iVar15 != auVar18._0_4_)) {
          auVar18._4_4_ = auVar18._0_4_;
          auVar18._8_8_ = 0;
          uVar5 = movmskps(iVar14,auVar18);
          auVar18._0_4_ = (float)(int)(iVar15 + (uVar5 & 1 ^ 1));
        }
        lVar12 = 0;
        if ((_DAT_142006904 <= auVar18._0_4_) &&
           (auVar18._0_4_ = auVar18._0_4_ - _DAT_142006904, auVar18._0_4_ < _DAT_142006904)) {
          lVar12 = -0x8000000000000000;
        }
        uVar11 = (longlong)auVar18._0_4_ + lVar12;
        if ((1 < uVar11) && ((ulonglong)(longlong)iVar14 < uVar11)) {
          uVar11 = uVar11 - (longlong)iVar14;
          uVar13 = (**(code **)(*(longlong *)param_1[8] + 0x2f0))();
          if (uVar13 < uVar11) {
            lVar12 = 0;
          }
          else {
            lVar12 = uVar13 - uVar11;
          }
          (**(code **)(*(longlong *)param_1[8] + 0x2e8))((longlong *)param_1[8],lVar12,1);
          if (uVar13 < uVar11) {
            uVar11 = uVar13;
          }
          param_1[0x35] = param_1[0x35] + uVar11;
        }
      }
      auVar23._0_4_ = *(float *)(param_1 + 0x34);
      if (auVar23._0_4_ <= 0.0) {
        uVar11 = (**(code **)(*(longlong *)param_1[8] + 0x2f8))();
        if ((longlong)uVar11 < 0) {
          auVar23._0_4_ = (float)uVar11;
        }
        else {
          auVar23._0_4_ = (float)(longlong)uVar11;
        }
      }
      fVar17 = (auVar23._0_4_ - fVar17) * fVar16 + fVar17;
      if (*(float *)(param_1 + 0x33) <= fVar17) {
        fVar17 = *(float *)(param_1 + 0x33);
      }
    }
    *(float *)((longlong)param_1 + 0x184) = fVar17;
    if ((*(char *)((longlong)param_1 + 0x17d) == '\0') ||
       (fVar17 = *(float *)(param_1 + 0x2c), auVar23._0_4_ = (float)FUN_140dd96e0(param_1),
       fVar17 < auVar23._0_4_)) {
      if ((*(float *)(param_1 + 0x2d) < *(float *)(param_1 + 0x2c) ||
           *(float *)(param_1 + 0x2d) == *(float *)(param_1 + 0x2c)) &&
         (cVar3 = (**(code **)(*(longlong *)param_1[8] + 0x3a8))(), cVar3 != '\x0e')) {
        (**(code **)(*param_1 + 0x168))(param_1,0xe);
      }
    }
    else {
      *(undefined1 *)((longlong)param_1 + 0x17d) = 0;
      (**(code **)(*param_1 + 0x168))(param_1,1);
    }
  }
  return;
}

