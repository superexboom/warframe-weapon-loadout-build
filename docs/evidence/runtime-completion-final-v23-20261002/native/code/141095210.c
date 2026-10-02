
void FUN_141095210(undefined8 param_1,undefined8 param_2,longlong *param_3)

{
  longlong lVar1;
  undefined1 uVar2;
  
  uVar2 = 1;
  lVar1 = *param_3;
  if (lVar1 != (ulonglong)*(uint *)(param_3 + 1) + lVar1) {
    do {
      FUN_140a3e6c0(lVar1 + 8,param_2,uVar2,1);
      uVar2 = 0;
      lVar1 = lVar1 + 0x128;
    } while (lVar1 != (ulonglong)*(uint *)(param_3 + 1) + *param_3);
  }
  return;
}

